import os, json
from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ["NOVA_EMBED_MODEL_ID"]  # amazon.nova-2-multimodal-embeddings-v1:0

_client = None


def _bedrock():
    """
    Build the Bedrock client on first use, not at import.

    Constructing it at module scope meant every importer paid for credential
    resolution -- including pytest merely *collecting* a test file that
    transitively imports this module. On a machine where that resolution is slow
    it broke collection outright with a connect timeout, failing tests that never
    intended to touch AWS.

    Adaptive retries with client-side rate limiting: indexing a real corpus is
    thousands of concurrent calls, and embed_many_texts deliberately lets
    exceptions propagate, so one transient ThrottlingException forty minutes into
    a run would otherwise discard the whole job. Adaptive mode backs off *and*
    throttles the client, which suits a long batch better than a fixed attempt
    count.

    Timeouts are generous and configurable. An earlier 15s connect timeout was
    right for production and wrong for a slow local environment, where it turned
    a delay into a hard failure.

    The `import boto3` lives in here rather than at module scope. Making only the
    client lazy fixed half the problem: importing the SDK is itself the expensive
    part -- minutes on a machine with slow disk -- and every importer paid it
    whether or not it ever reached AWS.
    """
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "bedrock-runtime",
            region_name=REGION,
            config=Config(
                retries={"max_attempts": 8, "mode": "adaptive"},
                read_timeout=int(os.environ.get("BEDROCK_READ_TIMEOUT", "60")),
                connect_timeout=int(os.environ.get("BEDROCK_CONNECT_TIMEOUT", "60")),
            ),
        )
    return _client

def embed_one(
    text: str,
    *,
    purpose: str = "GENERIC_INDEX",
    dim: int = 1024,
    truncation_mode: str = "END",
) -> list[float]:
    

    """
    Nova Multimodal Embeddings (SINGLE_EMBEDDING) for TEXT.
    Schema: nova-multimodal-embed-v1
    """
    body = {
        "schemaVersion": "nova-multimodal-embed-v1",
        "taskType": "SINGLE_EMBEDDING",
        "singleEmbeddingParams": {
            "embeddingPurpose": purpose,          # e.g. GENERIC_INDEX, TEXT_RETRIEVAL
            "embeddingDimension": dim,            # 256 | 384 | 1024 | 3072
            "text": {
                "truncationMode": truncation_mode,  # START | END | NONE
                "value": text
            }
        }
    }

    resp = _bedrock().invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )

    payload = json.loads(resp["body"].read().decode("utf-8"))

    # Response schema: {"embeddings":[{"embeddingType":"TEXT","embedding":[...]}]}
    return payload["embeddings"][0]["embedding"]

import concurrent.futures
import os

# Bedrock has no batch endpoint for this model, so throughput comes from
# concurrency. Serial embedding meant one HTTP round trip per chunk: indexing a
# few thousand messages took roughly an hour, paid again on every re-index
# (ARCHITECTURE.md R9).
#
# Kept modest by default because the ceiling is an account-level Bedrock quota,
# not local CPU, and being throttled is slower than being patient. Raise it if
# your account has the headroom.
EMBED_CONCURRENCY = int(os.environ.get("EMBED_CONCURRENCY", "8"))


def embed_many_texts(
    texts: list[str],
    *,
    purpose: str = "GENERIC_INDEX",
    dim: int = 1024,
    max_workers: int = None,
    progress=None,
) -> list[list[float]]:
    """
    Embed many texts concurrently, preserving input order.

    boto3 clients are not thread-safe for sharing across threads in all cases,
    but invoke_model on a module-level client is safe here: botocore serializes
    request signing per call and holds no per-request state on the client.

    Order matters -- callers zip the result against their chunk list, so a
    reordered return would silently attach every embedding to the wrong chunk.
    Results are placed by index rather than appended.
    """
    if not texts:
        return []

    workers = max_workers or EMBED_CONCURRENCY
    vectors: list[list[float] | None] = [None] * len(texts)
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(embed_one, t, purpose=purpose, dim=dim): i
            for i, t in enumerate(texts)
        }
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            # Let exceptions propagate. A silently dropped embedding produces a
            # chunk that exists but can never be retrieved, which is worse than
            # a failed ingest you can retry.
            vectors[i] = fut.result()
            done += 1
            if progress and done % 25 == 0:
                progress(done, len(texts))

    if progress:
        progress(len(texts), len(texts))

    return vectors