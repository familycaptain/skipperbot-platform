"""
service_token.py — Issue auth tokens for companion services.

Companion services (skipperbot-voice, skipperbot-mobile, future ones) need a
Bearer token to authenticate their REST + websocket calls to the platform. This
script issues, lists, and revokes those tokens (stored hashed in
public.service_tokens).

Usage:
    python scripts/service_token.py create <label> [--user NAME] [--role ROLE]
    python scripts/service_token.py list
    python scripts/service_token.py revoke <token-id>

`create` prints the token ONCE — copy it into the companion service's .env as
SKIPPERBOT_TOKEN. Only its hash is stored. Optionally bind it to a real user
(--user) so per-user (IDOR) scoping applies; default role is 'member'.
"""

import argparse
import sys

# Allow running from the repo root (so `data_layer` imports resolve).
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))

from data_layer.service_tokens import (  # noqa: E402
    create_service_token,
    ensure_auth_schema,
    list_service_tokens,
    revoke_service_token,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage companion-service auth tokens.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="create a new service token")
    p_create.add_argument("label", help="a name, e.g. 'voice' or 'mobile-fleet'")
    p_create.add_argument("--user", default=None,
                          help="bind to this username (for per-user data scoping)")
    p_create.add_argument("--role", default="member", help="granted role (default: member)")

    sub.add_parser("list", help="list service tokens")

    p_revoke = sub.add_parser("revoke", help="revoke a token by id")
    p_revoke.add_argument("token_id")

    args = parser.parse_args()
    ensure_auth_schema()

    if args.cmd == "create":
        token_id, plaintext = create_service_token(args.label, bound_user=args.user, role=args.role)
        print(f"Created service token '{args.label}' (id: {token_id})")
        if args.user:
            print(f"  bound user: {args.user}  role: {args.role}")
        print("\n  Copy this into the companion service's .env (shown only once):\n")
        print(f"    SKIPPERBOT_TOKEN={plaintext}\n")
        return 0

    if args.cmd == "list":
        rows = list_service_tokens()
        if not rows:
            print("No service tokens.")
            return 0
        for r in rows:
            state = "REVOKED" if r.get("revoked_at") else "active"
            print(f"  {r['id']}  [{state}]  label={r['label']}  "
                  f"user={r.get('bound_user') or '-'}  role={r.get('role')}  "
                  f"last_used={r.get('last_used_at') or 'never'}")
        return 0

    if args.cmd == "revoke":
        ok = revoke_service_token(args.token_id)
        print(f"Revoked {args.token_id}." if ok else f"No active token with id {args.token_id}.")
        return 0 if ok else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
