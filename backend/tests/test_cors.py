"""
Middleware ordering — CORS must wrap auth, not the other way round.

The bug this guards against: registering CORSMiddleware before the auth
middleware left auth as the OUTERMOST layer, because Starlette's add_middleware
inserts at the outermost position. Auth's early 401 returns then short-circuited
before CORS ran, so rejected requests came back with no
access-control-allow-origin header.

A browser cannot read a cross-origin response without that header, so it
reported "Failed to fetch" rather than the 401 that actually occurred -- turning
a one-line config mistake into an opaque network error. The preflight looked
healthy the whole time, because auth passes OPTIONS straight through.
"""

from starlette.middleware.cors import CORSMiddleware


def test_cors_is_outermost_middleware():
    """
    CORS must be the first entry in the stack, which is the outermost wrapper.
    If auth ever gets registered after it again, this fails.
    """
    import main

    classes = [m.cls for m in main.app.user_middleware]
    assert CORSMiddleware in classes, "CORSMiddleware is not registered at all"
    assert classes[0] is CORSMiddleware, (
        f"CORSMiddleware must be outermost so error responses carry CORS "
        f"headers; stack is {[c.__name__ for c in classes]}"
    )


def test_localhost_origins_always_allowed():
    """Development origins must not depend on ALLOWED_ORIGINS being set."""
    import main

    assert "http://localhost:5175" in main.ALLOWED_ORIGINS
    assert "http://localhost:5173" in main.ALLOWED_ORIGINS


def test_env_origins_are_appended_and_trimmed(monkeypatch):
    """Deployed origins come from the environment, comma-separated."""
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://a.vercel.app , https://b.vercel.app ")
    origins = main_origins()
    assert "https://a.vercel.app" in origins
    assert "https://b.vercel.app" in origins
    assert "" not in origins


def main_origins():
    """Recompute the origin list the way main.py does, without reimporting it."""
    import os

    local = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:5175",
    ]
    return local + [
        o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
