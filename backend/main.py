import os
import math
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# import your pipeline pieces
from services.slack_export import parse_slack_export
from services.bedrock_embed import embed_one
from services.nova_extract import extract_decisions
from services.chunking import chunk_document
from services.db import get_pool, close_pool
from services.retrieval import retrieve_top_k
from services.ingest import ingest_slack_export

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
API_KEY = os.environ.get("API_KEY", "recall-demo-key")
USE_DB = bool(DATABASE_URL)

# ---------------------------------------------------------------------------
# In-memory fallback (kept for when no DB is configured)
# ---------------------------------------------------------------------------
INDEX = None

def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)

def build_index():
    docs = parse_slack_export("slack_export")
    chunks = []
    for d in docs:
        chunks.extend(chunk_document(d))
    for c in chunks:
        c["embedding"] = embed_one(c["text"])
    return chunks

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):
    if USE_DB:
        await get_pool()
    yield
    await close_pool()

app = FastAPI(title="Recall API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://localhost:5175"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth middleware  (Req C — static header fallback)
# Open paths that skip auth.
# ---------------------------------------------------------------------------
OPEN_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in OPEN_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    key = request.headers.get("x-api-key", "")
    org = request.headers.get("x-org-id", "")

    if key != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing x-api-key"})
    if not org:
        return JSONResponse(status_code=401, content={"detail": "Missing x-org-id header"})

    request.state.org_id = org
    return await call_next(request)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str
    org_id: str | None = None
    top_k: int | None = 8

class IngestRequest(BaseModel):
    export_dir: str = "slack_export"
    org_id: str | None = None

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# --- A) GET /health ---
@app.get("/health")
async def health():
    return {"status": "ok", "db": USE_DB}

@app.get("/")
async def root():
    return {"message": "Recall backend running", "db": USE_DB}

# --- A) POST /ingest ---
@app.post("/ingest")
async def ingest(req: IngestRequest, request: Request, background_tasks: BackgroundTasks):
    org_id = req.org_id or getattr(request.state, "org_id", "demo")

    if USE_DB:
        result = await ingest_slack_export(req.export_dir, org_id)
        return {"status": "done", **result}
    else:
        # In-memory: just rebuild the index
        global INDEX
        INDEX = build_index()
        return {"status": "done", "mode": "in-memory", "chunks": len(INDEX)}

# --- A) POST /query ---
@app.post("/query")
async def query(req: QueryRequest, request: Request):
    org_id = req.org_id or getattr(request.state, "org_id", "demo")
    top_k = req.top_k or 8

    qvec = embed_one(req.question, purpose="TEXT_RETRIEVAL")

    if USE_DB:
        top = await retrieve_top_k(qvec, org_id, k=top_k)
    else:
        global INDEX
        if INDEX is None:
            INDEX = build_index()
        scored = sorted(INDEX, key=lambda c: cosine(c["embedding"], qvec), reverse=True)
        top = scored[:top_k]

    extracted = extract_decisions(req.question, top)

    sources = []
    for t in top:
        chan = t.get("channel") or t.get("metadata", {}).get("channel") or ""
        title = "Slack"
        if chan:
            title = f"Slack · #{chan}"
        sources.append({
            "id": t.get("chunk_id", ""),
            "title": title,
            "excerpt": t.get("text", "")[:240],
        })

    return {"decisions": extracted.get("decisions", []), "sources": sources}

# --- A) GET /documents ---
@app.get("/documents")
async def list_documents(request: Request):
    org_id = getattr(request.state, "org_id", "demo")

    if not USE_DB:
        return {"documents": [], "detail": "No database configured; using in-memory mode"}

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, org_id, source, title,
               left(raw_text, 300) AS excerpt,
               metadata, created_at
        FROM documents
        WHERE org_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT 50
        """,
        org_id,
    )
    return {
        "documents": [
            {
                "id": str(r["id"]),
                "source": r["source"],
                "title": r["title"],
                "excerpt": r["excerpt"],
                "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    }

@app.get("/documents/{doc_id}")
async def get_document(doc_id: str, request: Request):
    if not USE_DB:
        raise HTTPException(404, "No database configured")

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM documents WHERE id = $1::uuid", doc_id
    )
    if not row:
        raise HTTPException(404, "Document not found")

    return {
        "id": str(row["id"]),
        "org_id": str(row["org_id"]),
        "source": row["source"],
        "title": row["title"],
        "raw_text": row["raw_text"],
        "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }