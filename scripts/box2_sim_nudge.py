"""Simulate the onboarding 24h proactive-nudge cycle (run INSIDE the agent container):
  docker compose exec -T agent python /app/scripts/box2_sim_nudge.py

Fast-forwards time (backdates chat turns + pending-DM state >24h so _dm_on_hold and
_user_recently_active stop holding), then triggers one goal-domain thinking cycle directly. Prints
the agenda (so you can see which topics were skipped=done) and the nudge it produced — so you can
check it (a) actually nags and (b) respects skipped/done topics. Then reply via box2_drive to test
handling on top of the nudge.
"""
import sys
sys.path.insert(0, "/app")  # so it imports app_platform/* when run as `python /app/scripts/...`
import asyncio, json
from datetime import datetime, timezone
from app_platform import config as pc
import apps.goals.data as g
from data_layer.db import execute
from data_layer.skipper_state import list_states, update_state
from apps.goals.domain import goal_domain_handler

GID = (pc.get("onboarding_seeded", scope="app:goals") or {}).get("goal_id")
USER = "rodney"

def agenda():
    return [p for p in g.get_projects_for_goal(GID) if not (p.get("name") or "").startswith("Try the")]

print("=== agenda BEFORE nudge (skipped topics show as 'done') ===")
for p in agenda():
    print(f"  {p.get('status'):12} {p.get('name')}")

# --- fast-forward 25h ---
execute("UPDATE chat_turns SET created_at = created_at - interval '25 hours'")
execute("UPDATE skipper_state SET created_at = created_at - interval '25 hours', "
        "updated_at = updated_at - interval '25 hours' WHERE state_type = 'pending_action'")
# also backdate the content.sent_at inside each pending_action (some checks read it)
for r in list_states(state_type="pending_action", status="active", limit=50):
    try:
        c = json.loads(r.get("content") or "{}")
        if "sent_at" in c:
            from datetime import timedelta
            c["sent_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
            update_state(r["id"], content=json.dumps(c))
    except Exception:
        pass
print("\n(fast-forwarded chat + pending DMs by 25h)")

print("\n=== triggering one goal-domain thinking cycle ===")
res = asyncio.get_event_loop().run_until_complete(
    goal_domain_handler({"name": GID}, {"remaining": 999_999}))
print("cycle result:", json.dumps(res, default=str)[:300])

print("\n=== pending nudges to the user AFTER the cycle ===")
for d in g.pending_dms_for_user(USER):
    print(f"  [{d.get('sent_at','')[:16]}] {d.get('dm_text','')[:160]}")
