import os
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from services.abstention import (
    RELEVANCE_THRESHOLD,
    log_abstention,
    near_misses,
    should_abstain,
)
from services.answer import attach_citations
from services.bedrock_embed import embed_one
from services.nova_extract import extract_decisions
from services.db import get_pool, close_pool
from services.retrieval import retrieve_top_k
from services.ingest import ingest_github_threads, ingest_slack_export

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
API_KEY = os.environ.get("API_KEY", "recall-demo-key")

# There is deliberately no in-memory fallback. See DECISIONS.md D4: a dual
# runtime path is how you ship a bug that only exists in production, and R10 in
# ARCHITECTURE.md was exactly that -- an org_id that was inert in memory and
# raised on a uuid cast the first time a real database was attached. A
# misconfigured deploy should refuse to start, not come up looking healthy while
# serving from an empty index.


@asynccontextmanager
async def lifespan(app):
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Recall requires Postgres with pgvector; "
            "there is no in-memory fallback (see DECISIONS.md D4). "
            "Copy backend/.env.example to backend/.env and fill in DATABASE_URL."
        )
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="Recall API", lifespan=lifespan)

# Deployed origins come from the environment; localhost stays for development.
# Comma-separated, e.g. ALLOWED_ORIGINS=https://canopy.vercel.app
LOCAL_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost:5175",
]
ALLOWED_ORIGINS = LOCAL_ORIGINS + [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

OPEN_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in OPEN_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    if request.headers.get("x-api-key", "") != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing x-api-key"})

    org = request.headers.get("x-org-id", "")
    if not org:
        return JSONResponse(status_code=401, content={"detail": "Missing x-org-id header"})

    # Validate here rather than letting a bad value reach a $1::uuid cast and
    # surface as a 500. The tenant boundary is real (DECISIONS.md D5), so a
    # malformed tenant is an auth failure, not an internal error.
    try:
        request.state.org_id = str(uuid.UUID(org))
    except ValueError:
        return JSONResponse(
            status_code=401,
            content={"detail": "x-org-id must be a UUID"},
        )

    return await call_next(request)


# CORS is registered AFTER auth_middleware, and the ordering is load-bearing.
#
# Starlette's add_middleware inserts at the OUTERMOST position, so the last
# middleware registered runs first. Registering CORS first put auth outside it,
# which meant auth's early 401 returns short-circuited before CORS ever ran --
# so a rejected request came back with no access-control-allow-origin header.
#
# The browser cannot read a cross-origin response without that header, so it
# reported an opaque "Failed to fetch" instead of the 401 that actually
# happened. The preflight looked fine throughout, because auth passes OPTIONS
# straight through, which made this hard to spot from the outside.
#
# With CORS outermost, every response carries the header, including errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str
    top_k: int | None = 8
    # org_id is deliberately absent. It comes from the x-org-id header only.
    # Previously the body value won over the header, which meant a client could
    # select its own tenant -- and did, sending the string "demo" (R10).


class IngestRequest(BaseModel):
    export_dir: str = "slack_export"


class GitHubIngestRequest(BaseModel):
    repo: str
    min_comments: int = 8
    max_threads: int = 300
    state: str = "all"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "db": True}


@app.get("/")
async def root():
    return {"message": "Recall backend running", "db": True}


@app.post("/ingest")
async def ingest(req: IngestRequest, request: Request):
    result = await ingest_slack_export(req.export_dir, request.state.org_id)
    return {"status": "done", **result}


@app.post("/ingest/github")
async def ingest_github(req: GitHubIngestRequest, request: Request):
    result = await ingest_github_threads(
        req.repo,
        request.state.org_id,
        min_comments=req.min_comments,
        max_threads=req.max_threads,
        state=req.state,
    )
    return {"status": "done", **result}


@app.post("/query")
async def query(req: QueryRequest, request: Request):
    org_id = request.state.org_id
    top_k = req.top_k or 8

    qvec = embed_one(req.question, purpose="TEXT_RETRIEVAL")
    top = await retrieve_top_k(qvec, org_id, k=top_k)

    # Decide on retrieval quality before calling the generator. Asking the model
    # whether it can answer invites it to say yes and confabulate, which is the
    # failure this exists to prevent (spec trap 4 / 1.2).
    abstain, top_score = should_abstain(top)
    if abstain:
        misses = near_misses(top)
        await log_abstention(
            org_id, req.question, top_score, RELEVANCE_THRESHOLD, len(top), misses
        )
        return {
            "abstained": True,
            "reason": "No indexed content was close enough to answer this confidently.",
            "decisions": [],
            "sources": [],
            "near_misses": misses,
            "top_score": top_score,
            "threshold": RELEVANCE_THRESHOLD,
            "retrieved_count": len(top),
        }

    extracted = extract_decisions(req.question, top)

    # Citations come from what the model actually cited, not from everything
    # retrieved (spec trap 4 / ARCHITECTURE.md R1). See services/answer.py.
    decisions, sources = attach_citations(extracted.get("decisions", []), top)

    return {
        "abstained": False,
        "decisions": decisions,
        "sources": sources,
        "top_score": top_score,
        "threshold": RELEVANCE_THRESHOLD,
        # Diagnostic: how much of what we retrieved was actually used. A large
        # gap is a signal that retrieval is returning noise.
        "retrieved_count": len(top),
    }


@app.get("/documents")
async def list_documents(request: Request):
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
        request.state.org_id,
    )

    # Real totals for the UI. The rows above are capped at 50, so counting them
    # would understate a larger corpus -- the Source Management page showed
    # "0 Total Items" against 100 indexed documents before this.
    totals = await pool.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM documents WHERE org_id = $1::uuid) AS documents,
          (SELECT count(*) FROM chunks    WHERE org_id = $1::uuid) AS chunks,
          (SELECT max(updated_at) FROM documents WHERE org_id = $1::uuid) AS last_indexed
        """,
        request.state.org_id,
    )

    return {
        "total_documents": totals["documents"],
        "total_chunks": totals["chunks"],
        "last_indexed": totals["last_indexed"].isoformat() if totals["last_indexed"] else None,
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
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM documents WHERE id = $1::uuid AND org_id = $2::uuid",
        doc_id,
        request.state.org_id,
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
