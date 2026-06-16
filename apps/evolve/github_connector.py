"""GitHub issue intake for Evolve (EVOLVE.md §5/§8).

Reads open issues from the configured repo via a Personal Access Token and maps each
to an Evolve work-item the pipeline can ingest at `s_issue`. Read-only by default —
honoring the GitHub write-boundary (only the operator publishes; the brain holds a
read-only deploy key). Posting an acknowledgement comment back is a SEPARATE, explicit
opt-in call (post_comment), never automatic.

stdlib-only (urllib) so it runs in the minimal box-1 venv. Config via env:
    GITHUB_TOKEN   — a PAT that can READ issues on GITHUB_REPO
    GITHUB_REPO    — owner/repo (default: familycaptain/skipperbot-platform)
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
DEFAULT_REPO = "familycaptain/skipperbot-platform"


def _token() -> str:
    return (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()


def _repo(repo: str | None = None) -> str:
    return repo or os.getenv("GITHUB_REPO") or DEFAULT_REPO


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skipper-evolve",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        raise RuntimeError(f"GitHub {method} {path} -> HTTP {e.code}: {detail}") from e


def list_open_issues(repo: str | None = None, token: str | None = None) -> list[dict]:
    """Open issues on the repo (pull requests excluded — GitHub returns them here too)."""
    token = token or _token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    repo = _repo(repo)
    out, page = [], 1
    while True:
        data = _request("GET", f"/repos/{repo}/issues?state=open&per_page=100&page={page}", token)
        if not isinstance(data, list) or not data:
            break
        out.extend(i for i in data if "pull_request" not in i)
        if len(data) < 100:
            break
        page += 1
    return out


def _operator_logins() -> set:
    """GitHub logins treated as the operator (their requests ARE the vision — skip vision-fit).
    Configure via EVOLVE_OPERATOR_GH (comma-separated). Empty = trust no one (default)."""
    return {s.strip().lower() for s in (os.getenv("EVOLVE_OPERATOR_GH", "") or "").split(",") if s.strip()}


def issue_to_work_item(issue: dict, repo: str | None = None) -> dict:
    """Map a GitHub issue to an Evolve work-item (the pipeline's s_issue input)."""
    repo = _repo(repo)
    author = (issue.get("user") or {}).get("login", "")
    return {
        "title": issue.get("title", "") or "",
        "body": issue.get("body") or "",
        "source": f"github:{repo}#{issue.get('number')}",
        "url": issue.get("html_url", ""),
        "number": issue.get("number"),
        "labels": [l.get("name") for l in issue.get("labels", [])],
        "author": author,
        "from_operator": author.lower() in _operator_logins(),   # operator-authored → skip vision-fit
    }


def post_comment(number: int, body: str, repo: str | None = None, token: str | None = None) -> dict:
    """Post an acknowledgement comment on an issue (explicit opt-in; write-boundary).
    Requires a token with Issues:write. Never called automatically."""
    token = token or _token()
    return _request("POST", f"/repos/{_repo(repo)}/issues/{number}/comments", token, {"body": body})


def close_issue(number: int, comment: str = "", repo: str | None = None, token: str | None = None) -> dict:
    """Close an issue (optionally leaving a comment first). Used to 'close the loop' only after the
    operator VERIFIES the shipped change actually works — never on merge alone. Write-boundary:
    requires a token with Issues:write."""
    token = token or _token()
    if comment:
        _request("POST", f"/repos/{_repo(repo)}/issues/{number}/comments", token, {"body": comment})
    return _request("PATCH", f"/repos/{_repo(repo)}/issues/{number}", token, {"state": "closed"})


def whoami(token: str | None = None) -> dict:
    return _request("GET", "/user", token or _token())
