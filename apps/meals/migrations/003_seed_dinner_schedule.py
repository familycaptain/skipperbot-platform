"""Seed the nightly dinner-check scheduled job (9pm daily)."""
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
            VALUES ('j-meals-dinner-check', 'Nightly Dinner Check', 'meals_dinner_check',
                    'Check if dinner was logged tonight; prompt the user if not',
                    '0 21 * * *', 'user', 'active', 'system', now(),
                    '{}'::jsonb, 'Scheduled')
            ON CONFLICT (id) DO UPDATE SET
                schedule = '0 21 * * *', status = 'active'
        """)
    conn.commit()
    print("Seeded: j-meals-dinner-check  cron='0 21 * * *' (9pm every night)")
