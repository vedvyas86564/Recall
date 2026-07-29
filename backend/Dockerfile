# Canopy backend.
#
# Vercel is not a target for this service -- see DECISIONS.md D15. It needs a
# long-lived process: an asyncpg pool against Supabase's session pooler, and
# /query routinely takes 5-10s (one embedding call, retrieval, one Nova Lite
# call), which exceeds Vercel Hobby's 10s function ceiling.
#
# This image runs anywhere that hosts a container: Render, Fly, Railway, Cloud Run.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so code edits do not invalidate the install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hosts inject PORT. Bind 0.0.0.0 -- the default 127.0.0.1 is unreachable from
# outside the container and presents as a silent health-check failure.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
