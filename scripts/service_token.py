"""
service_token.py — Issue auth tokens for companion services.

Companion services (skipperbot-voice, skipperbot-mobile, future ones) need
a Bearer token to authenticate their REST calls to the platform. This script
issues tokens and stores them in the platform's token table.

Usage:
    python scripts/service_token.py create voice
    python scripts/service_token.py list
    python scripts/service_token.py revoke <token-id>

The created token gets printed once; the companion service stores it in its
own .env as SKIPPERBOT_TOKEN. The same operation is available through the
Settings app under "Service Tokens".

Placeholder — full implementation lands in Chunk 2.
"""

import sys


def main() -> int:
    print("scripts/service_token.py — placeholder. Full implementation in Chunk 2.")
    print("Companion services (voice/mobile) will use these tokens for /api/voice/*")
    print("and /api/mobile/* authentication.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
