"""Seed the daily bounty digest scheduled job (8am every day)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../..")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../..", ".env"))

from data_layer.db import get_conn

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO app_jobs.jobs (id, name, job_type, description, schedule, notify_user,
                              status, created_by, created_at, config, progress)
            VALUES ('j-bounties-daily-digest', 'Daily Bounty Digest', 'bounty_daily_digest',
                    'Send daily bounty board DM to kids (open bounties + balance) and parents (pending approvals)',
                    '0 8 * * *', 'user', 'active', 'system', now(),
                    '{}'::jsonb, 'Scheduled')
            ON CONFLICT (id) DO UPDATE SET
                schedule = '0 8 * * *', status = 'active'
        """)
    conn.commit()
    print("Seeded: j-bounties-daily-digest  cron='0 8 * * *' (8am every day)")
