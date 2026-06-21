#!/usr/bin/env bash
#
# Completeness gate for MODEL_FLEXIBILITY P1 (issue #39).
#
# Proves ZERO direct OpenAI usage in PRODUCT code — every model call must go through the
# providers/ connector. Run it, don't eyeball it.
#
# Scope = product Python, EXCLUDING:
#   - providers/            (the connector + its lazy client IS the sanctioned home)
#   - config.py             (the lazy `openai_client` accessor for dev harnesses)
#   - tests/, scripts/      (test/dev harnesses)
#   - apps/evolve/          (separate subsystem — stays Claude Code, never on ChatProvider)
#   - test_chat.py          (root dev/test harness)
#   - .venv/, node_modules/, web/
#
# Exits non-zero (with the offending file:line) on any hit.
set -euo pipefail
cd "$(dirname "$0")/.."

PATTERN='openai_client|chat\.completions\.create\(|embeddings\.create\('
EXCLUDES='/\.venv/|/node_modules/|/web/|/tests/|/scripts/|/apps/evolve/|/providers/|(^|/)config\.py:|(^|/)test_chat\.py:'

hits="$(grep -rnE "$PATTERN" --include='*.py' . 2>/dev/null | grep -vE "$EXCLUDES" || true)"

if [ -n "$hits" ]; then
  echo "[check-no-direct-openai] FAIL — direct OpenAI usage found in product code (issue #39):"
  echo "$hits"
  echo
  echo "Route the call through providers/ (get_chat_provider()/get_embedding_provider() or providers.compat.chat_completion)."
  exit 1
fi

# The eager module-level singleton must be gone (a lazy accessor is allowed).
if grep -nE '^openai_client[[:space:]]*=[[:space:]]*OpenAI\(' config.py >/dev/null 2>&1; then
  echo "[check-no-direct-openai] FAIL — config.py still builds an eager openai_client singleton."
  exit 1
fi

echo "[check-no-direct-openai] OK — zero direct OpenAI usage in product code; no eager config singleton."
