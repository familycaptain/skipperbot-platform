"""Test setup: force the onboarding goal (and its projects) to CANCELLED, mimicking a user who
told Skipper to stop onboarding. Run inside the box2 agent container: python3 /app/scripts/box2_cancel_onboarding.py"""
import sys
sys.path.insert(0, "/app")
from app_platform import config as platform_config
import apps.goals.data as dl

seeded = platform_config.get("onboarding_seeded", scope="app:goals") or {}
gid = seeded.get("goal_id")
print("onboarding goal_id:", gid)
g = next((x for x in dl.list_entities("g-") if x.get("id") == gid), None)
if g:
    g["status"] = "cancelled"
    dl.save_entity(g)
for p in dl.get_projects_for_goal(gid):
    p["status"] = "cancelled"
    dl.save_entity(p)
g2 = next((x for x in dl.list_entities("g-") if x.get("id") == gid), None)
projs = dl.get_projects_for_goal(gid)
print("goal status now:", g2 and g2.get("status"))
print("project statuses:", [p.get("status") for p in projs][:6], f"(of {len(projs)})")
