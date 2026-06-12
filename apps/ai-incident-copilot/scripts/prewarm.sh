#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
#
# Idempotent prewarm — run ~30 s before pressing record.
# Warms three independent things:
#   1) Oracle listener + connection pool inside the container
#   2) Ollama (loads llama3.1:8b weights into memory; first call after this is ~1.7s vs ~28s cold)
#   3) The Python agent graph: MiniLM model load, langgraph compile, oracledb thin pool primed
#
# Safe to re-run. Exits non-zero only on a real failure (a missing dep / dead service),
# never on a cache-already-warm condition.

set -euo pipefail

CONTAINER="${ORACLE_CONTAINER:-oracle26ai}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
API_URL="${COPILOT_API_URL:-http://127.0.0.1:8000}"

echo "[prewarm] 1/3 — Oracle listener + connection pool"
docker exec "$CONTAINER" sh -c \
    "echo 'SELECT COUNT(*) FROM incidents;' | sqlplus -S -L copilot/Welcome_123@FREEPDB1" \
    >/dev/null
echo "  ok"

echo "[prewarm] 2/3 — Ollama ($OLLAMA_MODEL into VRAM)"
curl -sS "$OLLAMA_URL/api/generate" \
    -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"warm\",\"stream\":false}" \
    >/dev/null
echo "  ok"

echo "[prewarm] 3/3 — agent graph (MiniLM + langgraph + thin pool)"
# A throwaway POST that exercises every cold-cacheable thing in the agent path.
# We keep the prompt short so this finishes in ~3-6 s once Ollama is warm.
http_code=$(curl -sS -o /tmp/prewarm_diag.json -w "%{http_code}" \
    -X POST "$API_URL/diagnose" \
    -H "Content-Type: application/json" \
    -d '{"query":"warm"}')
if [ "$http_code" != "200" ]; then
    echo "[prewarm] /diagnose returned $http_code (is uvicorn up at $API_URL?)" >&2
    cat /tmp/prewarm_diag.json >&2 || true
    exit 1
fi
echo "  ok"

echo "[prewarm] done — first on-camera /diagnose call should be ~5-8 s end-to-end."
