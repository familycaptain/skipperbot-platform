#!/usr/bin/env python3
"""Box-2 fixture snapshot/restore (Phase 1) — reproducible acceptance starting state.

box 2's DB persists across `skipper update`, so test data drifts run-to-run. This captures a known
baseline ONCE (`snapshot`) and restores it before each acceptance run (`reset`), so scenarios always
start from an identical state. box 2 is the disposable validator, so a full-DB reset is fine.

  python box2_fixture.py snapshot   # capture the current DB as the baseline fixture
  python box2_fixture.py reset      # restore the DB to the fixture, then bring the app back healthy
  python box2_fixture.py status     # show the fixture + a row-count sanity check
"""
import argparse, json, os, subprocess, time, urllib.request

DB_C = "skipperbot-platform-db-1"
AGENT_C = "skipperbot-platform-agent-1"
DBNAME = "skipperbot"
DBUSER = "skipperbot_user"
FIXTURE_HOST = os.path.expanduser("~/box2-fixture.dump")
FIXTURE_IN_DB = "/tmp/box2-fixture.dump"
STATUS_URL = "http://localhost:8000/api/onboarding/status"


def run(cmd, timeout=300, check=True):
    print(f"  $ {cmd}", flush=True)
    r = subprocess.run(cmd, shell=True, text=True, timeout=timeout,
                       capture_output=True)
    if r.stdout.strip(): print(r.stdout.strip())
    if r.returncode != 0:
        print(f"  ! rc={r.returncode}: {r.stderr.strip()[:500]}")
        if check: raise RuntimeError(f"command failed: {cmd}")
    return r


def healthy():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=4) as r:
            return bool(json.loads(r.read()).get("db_ok"))
    except Exception:
        return False


def wait_healthy(timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if healthy(): return round(time.time() - t0, 1)
        time.sleep(5)
    return None


def snapshot():
    run(f"docker exec {DB_C} pg_dump -U {DBUSER} -d {DBNAME} -Fc -f {FIXTURE_IN_DB}")
    run(f"docker cp {DB_C}:{FIXTURE_IN_DB} {FIXTURE_HOST}")
    size = os.path.getsize(FIXTURE_HOST)
    print(json.dumps({"snapshot": FIXTURE_HOST, "bytes": size}))


def reset():
    if not os.path.exists(FIXTURE_HOST):
        raise SystemExit("no fixture — run `box2_fixture.py snapshot` first")
    t0 = time.time()
    run(f"docker cp {FIXTURE_HOST} {DB_C}:{FIXTURE_IN_DB}")
    # stop the app so there are no live connections during the drop/restore
    run(f"docker stop {AGENT_C}")
    # drop + recreate + restore (connected to the maintenance db). FORCE severs any stray conns.
    psql = f'docker exec {DB_C} psql -U {DBUSER} -d postgres -v ON_ERROR_STOP=1 -c'
    run(f'{psql} "DROP DATABASE IF EXISTS {DBNAME} WITH (FORCE);"')
    run(f'{psql} "CREATE DATABASE {DBNAME} OWNER {DBUSER};"')
    run(f"docker exec {DB_C} pg_restore -U {DBUSER} -d {DBNAME} --no-owner {FIXTURE_IN_DB}", check=False)
    # bring the app back (start re-runs the entrypoint -> rebuilds UI + reconnects)
    run(f"docker start {AGENT_C}")
    elapsed = wait_healthy()
    print(json.dumps({"reset": True, "healthy": elapsed is not None,
                      "ready_after_s": elapsed, "total_s": round(time.time() - t0, 1)}))


def status():
    have = os.path.exists(FIXTURE_HOST)
    info = {"fixture": FIXTURE_HOST, "exists": have,
            "bytes": os.path.getsize(FIXTURE_HOST) if have else 0,
            "app_healthy": healthy()}
    try:
        r = run(f'docker exec {DB_C} psql -U {DBUSER} -d {DBNAME} -tAc '
                f'"SELECT count(*) FROM users"', check=False)
        info["users_in_db"] = r.stdout.strip()
    except Exception:
        pass
    print(json.dumps(info, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("snapshot", "reset", "status"):
        sub.add_parser(c)
    a = ap.parse_args()
    {"snapshot": snapshot, "reset": reset, "status": status}[a.cmd]()


if __name__ == "__main__":
    main()
