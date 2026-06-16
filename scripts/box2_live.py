#!/usr/bin/env python3
"""Box-2 live-validation lifecycle controller (runs ON box 2).

Deploys a branch onto box 2's live dockerized Skipper, waits until it's actually serving, and
resets back to baseline. The deploy primitive is the SAME command the operator runs by hand —
`skipper update` — invoked non-interactively (SKIPPER_NO_FOLLOW=1) so it returns once healthy
instead of tailing the boot log forever. We never reinvent the deploy plumbing; we just call it.

  python box2_live.py deploy <branch>   # checkout <branch> -> skipper update -> wait healthy
  python box2_live.py reset             # deploy the baseline branch (release)
  python box2_live.py health            # report / wait for healthy
"""
import argparse, json, os, subprocess, time, urllib.request

REPO = os.path.expanduser("~/repos/skipperbot-platform")
BASELINE = "release"
PORT = int(os.environ.get("SKIPPERBOT_PORT", "8000"))
STATUS_URL = f"http://localhost:{PORT}/api/onboarding/status"


def sh(cmd, timeout=900):
    print(f"  $ {cmd}", flush=True)
    return subprocess.run(cmd, shell=True, cwd=REPO, text=True, timeout=timeout)


def healthy():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=4) as r:
            return bool(json.loads(r.read()).get("db_ok"))
    except Exception:
        return False


def wait_healthy(timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if healthy():
            return round(time.time() - t0, 1)
        time.sleep(5)
    return None


def deploy(branch):
    t0 = time.time()
    print(f"== deploy {branch} ==", flush=True)
    if sh("git fetch origin --prune").returncode != 0:
        return {"ok": False, "stage": "fetch"}
    if sh(f"git checkout -B {branch} origin/{branch}").returncode != 0:
        return {"ok": False, "stage": "checkout", "branch": branch}
    # THE deploy primitive — exactly what the operator runs, just non-interactive
    rc = sh("SKIPPER_NO_FOLLOW=1 ./skipper.sh update", timeout=900).returncode
    elapsed = wait_healthy()
    return {"ok": elapsed is not None, "branch": branch, "update_rc": rc,
            "healthy": elapsed is not None, "ready_after_s": elapsed,
            "total_s": round(time.time() - t0, 1),
            "head": subprocess.run("git rev-parse --short HEAD", shell=True, cwd=REPO,
                                   text=True, capture_output=True).stdout.strip()}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deploy"); d.add_argument("branch")
    sub.add_parser("reset")
    sub.add_parser("health")
    a = ap.parse_args()
    if a.cmd == "deploy":
        print(json.dumps(deploy(a.branch), indent=2))
    elif a.cmd == "reset":
        print(json.dumps(deploy(BASELINE), indent=2))
    elif a.cmd == "health":
        e = wait_healthy(120)
        print(json.dumps({"healthy": e is not None, "ready_after_s": e}))


if __name__ == "__main__":
    main()
