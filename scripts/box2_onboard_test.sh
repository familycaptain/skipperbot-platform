#!/usr/bin/env bash
#
# box2_onboard_test.sh — drive a full first-run onboarding conversation on box2 (agenda AND the
# app-tour phase) and report the outcome (per-turn tools/tokens + agenda/tour/goal state). Used to
# iterate on onboarding behavior until it's right. Pass --fresh to drop the DB first.
#
#   ./box2_onboard_test.sh --fresh
#
set -uo pipefail
cd ~/repos/skipperbot-platform
[ "${1:-}" = "--fresh" ] && { bash scripts/box2_fresh_install.sh >/dev/null 2>&1 && echo "(fresh install)"; }
python3 ~/box2_drive.py signup rodney testpass123 Rodney >/dev/null 2>&1

# Agenda turns, then continuers to exercise the app-tour phase + a clean opt-out to close.
TURNS=(
  "hi"
  "Me (Rodney), my wife Sarah, and kids Emma 8 and Jack 5. Want help with reminders and kid chores."
  "School pickup at 3pm weekdays, and a bedtime reminder at 8pm."
  "We're in Austin, Texas — I'll set it in Settings."
  "Skip Discord for now."
  "No other integrations right now, thanks."
  "Sounds good — yes, let's set up the kid chores."
  "Rotating weekly. Emma: trash + dishes; Jack: tidy room + feed the cat."
  "That's perfect — I'm all set, thanks!"
)
i=0
for t in "${TURNS[@]}"; do
  i=$((i+1))
  rep=$(python3 ~/box2_drive.py say "$t" 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print((d.get('skipper') or '').replace(chr(10),' ')[:150])" 2>/dev/null)
  echo "T$i «${t:0:44}» -> $rep"
done

echo "--- per-turn rounds/tools/tokens ---"
docker compose logs --tail 160 agent 2>&1 | grep "AGENT_LOOP: complete" | tail -9
echo "--- onboarding outcome ---"
docker compose exec -T agent python -c "
from collections import Counter
from app_platform import config as pc
import apps.goals.data as g
gid=(pc.get('onboarding_seeded',scope='app:goals') or {}).get('goal_id')
goal=next((x for x in g.list_entities('g-') if x.get('id')==gid), None)
ag=[]; tours=[]
for p in g.get_projects_for_goal(gid):
    (tours if (p.get('name') or '').startswith('Try the') else ag).append(p)
print('GOAL status:', goal.get('status'))
print('agenda:', dict(Counter(p.get('status') for p in ag)))
print('tours :', dict(Counter(p.get('status') for p in tours)), '(of', len(tours), ')')
print('tours touched:', [p.get('name') for p in tours if p.get('status')!='not_started'])
from data_layer.db import get_conn
with get_conn() as c, c.cursor() as cur:
    cur.execute(\"SELECT count(*) FROM memories WHERE content ILIKE %s\", ('%household: Rodney%',))
    print('duplicate household memories:', cur.fetchone()[0], '(want ~1)')
"
