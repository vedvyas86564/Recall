import os, json, re
import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv(override=True)

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ["NOVA_LITE_MODEL_ID"]

_client = None


def _bedrock():
    """
    Lazy, for the same reason as services/bedrock_embed: a client built at
    import time makes every importer pay for credential resolution, including
    pytest collecting a test file that never calls AWS.
    """
    global _client
    if _client is None:
        _client = boto3.client(
            "bedrock-runtime",
            region_name=REGION,
            config=Config(
                retries={"max_attempts": 6, "mode": "adaptive"},
                read_timeout=int(os.environ.get("BEDROCK_READ_TIMEOUT", "60")),
                connect_timeout=int(os.environ.get("BEDROCK_CONNECT_TIMEOUT", "60")),
            ),
        )
    return _client

def safe_json_parse(raw: str) -> dict:
    if not raw:
        return {"decisions": []}

    t = raw.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)

    try:
        return json.loads(t)
    except Exception:
        pass

    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    return {"decisions": []}

def extract_decisions(question: str, chunks: list[dict]) -> dict:
    evidence = [{"chunk_id": c["chunk_id"], "text": c["text"][:1800]} for c in chunks]

    instruction = """
You are an information extraction engine.
Return STRICT JSON only (no markdown, no commentary).

Schema:
{
  "decisions": [
    {
      "title": "string",
      "decision": "string",
      "owner": "string (empty if unknown)",
      "alternatives": ["string"],
      "commitments": ["string"],
      "unresolved_threads": ["string"],
      "evidence_chunk_ids": ["string"]
    }
  ]
}

Rules:
- Only use the evidence provided.
- If owner is not explicitly stated, set owner to "".
- If no supported decisions exist, return {"decisions": []}.
- Every decision must include evidence_chunk_ids referencing provided chunk_id values.
""".strip()

    user_payload = {"question": question, "evidence": evidence}

    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": instruction},
                    {"text": json.dumps(user_payload)}
                ]
            }
        ]
    }

    resp = _bedrock().invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )

    payload = json.loads(resp["body"].read().decode("utf-8"))

    if "output" in payload:
        content = payload["output"].get("message", {}).get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            return safe_json_parse(content[0].get("text", ""))

    if "message" in payload:
        content = payload["message"].get("content", [])
        if content and isinstance(content, list) and "text" in content[0]:
            return safe_json_parse(content[0].get("text", ""))

    if "results" in payload and payload["results"]:
        out = payload["results"][0].get("outputText")
        if out:
            return safe_json_parse(out)

    raise RuntimeError(f"Unexpected Nova Lite response keys: {list(payload.keys())} | payload={payload}")