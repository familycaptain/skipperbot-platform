#!/usr/bin/env python3
"""Evolve build guard — flag one-directional dependency-rule violations a change INTRODUCES.

The rule (CHARTER / ARCHITECTURE.md): apps may depend on the platform; the **platform must never
depend on an app**; **apps must not depend on each other's internals**. The Gate-1 architecture
review judges intent (before code), and box-2 validate runs tests — neither catches *where* the
implement agent actually put the code. This deterministic check closes that gap: it parses the
imports of every CHANGED .py file and fails if any crosses a boundary the wrong way.

  python3 scripts/evolve_dep_check.py [repo_or_worktree_dir] [base_ref]   # default . release

Exit 0 = clean, 1 = violations. Prints JSON. Run it in the feature worktree before pushing Gate 2.
"""
import ast, json, os, subprocess, sys

REPO = sys.argv[1] if len(sys.argv) > 1 else "."
BASE = sys.argv[2] if len(sys.argv) > 2 else "release"

# platform code (must never import an app): the platform package, the shared data layer,
# and the top-level modules (agent loop, chat, tool router, …).
_PLATFORM_PREFIXES = ("app_platform/", "data_layer/")


def _changed_py():
    files = set()
    for args in (["diff", "--name-only", BASE], ["diff", "--name-only", BASE, "--cached"]):
        out = subprocess.run(["git", "-C", REPO, *args], text=True, capture_output=True).stdout
        files.update(l.strip() for l in out.splitlines() if l.strip())
    return [f for f in files if f.endswith(".py") and os.path.exists(os.path.join(REPO, f))]


def _imports_from_src(src):
    try:
        tree = ast.parse(src)
    except Exception:
        return set()
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module)
    return mods


def _new_imports(rel):
    """Imports this change ADDED to the file (HEAD minus BASE) — so pre-existing baseline debt
    in a touched file isn't flagged, only what the change newly introduces."""
    try:
        head = _imports_from_src(open(os.path.join(REPO, rel)).read())
    except Exception:
        return set()
    r = subprocess.run(["git", "-C", REPO, "show", f"{BASE}:{rel}"], text=True, capture_output=True)
    base = _imports_from_src(r.stdout) if r.returncode == 0 else set()   # rc!=0 → new file
    return head - base


def _app_of(path):
    p = path.split("/")
    return p[1] if len(p) >= 2 and p[0] == "apps" else None


def _is_platform(path):
    return path.startswith(_PLATFORM_PREFIXES) or "/" not in path


def _violation(path, mod):
    if not (mod == "apps" or mod.startswith("apps.")):
        return None
    target = mod.split(".")[1] if len(mod.split(".")) > 1 else "?"
    if _is_platform(path):
        return (f"PLATFORM `{path}` imports app `{target}` (`{mod}`) — the platform must never "
                f"depend on an app. Move the shared code into the platform (app_platform).")
    src = _app_of(path)
    if src and target != src and target != "?":
        return (f"app `{src}` (`{path}`) imports another app `{target}` (`{mod}`) — apps must not "
                f"depend on each other's internals. Put shared code in the platform.")
    return None


def main():
    findings = []
    for f in _changed_py():
        for mod in sorted(_new_imports(f)):
            v = _violation(f, mod)
            if v:
                findings.append({"file": f, "import": mod, "violation": v})
    print(json.dumps({"ok": not findings, "violations": findings}, indent=2))
    sys.exit(0 if not findings else 1)


if __name__ == "__main__":
    main()
