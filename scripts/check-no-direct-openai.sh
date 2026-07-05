#!/usr/bin/env bash
#
# Completeness gate for MODEL_FLEXIBILITY P1 (issue #39).
#
# Proves ZERO direct OpenAI usage in PRODUCT code — every model call must go through the
# providers/ connector. Run it, don't eyeball it.
#
# Scope = product Python, EXCLUDING:
#   - providers/            (the connector + its lazy client IS the sanctioned home)
#   - tests/, scripts/      (test/dev harnesses)
#   - test_chat.py          (root dev/test harness)
#   - .venv/, node_modules/, web/
#
# NOTE (#44/#71): config.py NO LONGER exposes an `openai_client` accessor — the LLM path is
# provider-agnostic and resolves connector+model+key from the selected tier. config.py is no
# longer excluded; any lingering `config.openai_client` reference in product code is a real bug
# and this gate will now catch it.
#
# Exits non-zero (with the offending file:line) on any hit.
set -euo pipefail
cd "$(dirname "$0")/.."

PATTERN='openai_client|chat\.completions\.create\(|embeddings\.create\('
EXCLUDES='/\.venv/|/node_modules/|/web/|/tests/|/scripts/|/providers/|(^|/)test_chat\.py:'

hits="$(grep -rnE "$PATTERN" --include='*.py' . 2>/dev/null | grep -vE "$EXCLUDES" || true)"

if [ -n "$hits" ]; then
  echo "[check-no-direct-openai] FAIL — direct OpenAI usage found in product code (issue #39/#44/#71):"
  echo "$hits"
  echo
  echo "Route the call through providers/ (resolve_chat/resolve_embedding, get_chat_provider()/get_embedding_provider(), or providers.compat.chat_completion)."
  exit 1
fi

# config.py must build NO OpenAI client — neither an eager singleton nor a lazy accessor (#44/#71).
if grep -nE 'openai_client|OpenAI\(' config.py >/dev/null 2>&1; then
  echo "[check-no-direct-openai] FAIL — config.py still references an OpenAI client (must be provider-agnostic)."
  exit 1
fi

echo "[check-no-direct-openai] OK — zero direct OpenAI usage in product code; config.py builds no OpenAI client."
