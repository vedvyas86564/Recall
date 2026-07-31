import os, json, re
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

    The `import boto3` moved in here too. Making only the *client* lazy fixed
    half the problem -- importing the SDK is itself the expensive part, measured
    at minutes on a machine with slow disk, and every importer was still paying
    it whether or not it ever called AWS.
    """
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

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

def build_request_body(question: str, chunks: list[dict]) -> dict:
    """
    The Bedrock request payload, split out so it can be asserted on.

    Separate from extract_decisions because the sampling settings below are the
    kind of thing that regresses silently -- nothing fails, the numbers just get
    noisy again -- and a test that pins them should not have to stand up a
    Bedrock client to do it.
    """
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
        ],
        # Greedy decoding. Left at the model default until now, which made this
        # call the only nondeterministic step in the pipeline: two eval runs over
        # an identical corpus, with identical retrieval, disagreed on 25% of
        # citation slots across 12 of 39 questions.
        #
        # That is a measurement problem -- citation precision cannot be compared
        # between single runs if a quarter of it is sampling noise -- but the
        # product problem is worse. Asking the same question twice returned
        # different citations, in a tool whose entire claim is that you can check
        # its work. Extraction here is not a creative task; it reads evidence and
        # reports what is in it, and there is no version of that where sampling
        # helps.
        "inferenceConfig": {"temperature": 0.0, "topP": 1.0},
    }

    return body


def extract_decisions(question: str, chunks: list[dict]) -> dict:
    body = build_request_body(question, chunks)

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