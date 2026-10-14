#!/bin/sh
# Launch the Campus Customs MCP server with whichever Python has fastmcp installed.
#
# .mcp.json used to hard-code ./.venv/bin/python, which broke for anyone who cloned this
# repo and named their virtualenv something else. This tries the usual places and falls
# back to the system interpreter, so the server starts as long as fastmcp is importable
# somewhere.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)

for PY in "$ROOT/.venv/bin/python" "$ROOT/venv/bin/python" "$ROOT/.env/bin/python" python3 python; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c "import fastmcp" >/dev/null 2>&1; then
    exec "$PY" "$ROOT/mcp_server/server.py" "$@"
  fi
done

echo "campus-customs: no Python with fastmcp found." >&2
echo "Set one up with:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
exit 1
