#!/bin/bash
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
uv pip install --system -r "$CLAUDE_PROJECT_DIR/requirements.txt" --quiet
