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
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
DEFAULT_REPO = "familycaptain/skipperbot-platform"


def _load_dotenv_once() -> None:
    """Load repo-root .env into os.environ (setdefault — never clobber a real env var). The loop's
    process env does NOT carry GITHUB_TOKEN, and a bare `python3 -c "import github_connector; ...
    create_issue(...)"` (how the bug-scout one-liner runs) wouldn't otherwise see it — so the
    documented file-an-issue mechanism would silently fail with 'GITHUB_TOKEN is not set'. Load it
    here so create_issue works regardless of how it's invoked."""
    if getattr(_load_dotenv_once, "_done", False):
        return
    _load_dotenv_once._done = True
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    envf = os.path.join(root, ".env")
    if not os.path.exists(envf):
        return
    for line in open(envf):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _token() -> str:
    _load_dotenv_once()
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


EVIDENCE_BRANCH = "evolve-evidence"


def _ensure_evidence_branch(token: str, repo: str) -> None:
    """Create the `evolve-evidence` branch (off the default branch) if missing — keeps screenshot
    binaries OFF main/release while still giving GitHub a raw URL to render them inline in a comment."""
    r = _repo(repo)
    try:
        _request("GET", f"/repos/{r}/git/ref/heads/{EVIDENCE_BRANCH}", token)
        return  # already exists
    except RuntimeError:
        pass
    default = _request("GET", f"/repos/{r}", token)["default_branch"]
    sha = _request("GET", f"/repos/{r}/git/ref/heads/{default}", token)["object"]["sha"]
    try:
        _request("POST", f"/repos/{r}/git/refs", token,
                 {"ref": f"refs/heads/{EVIDENCE_BRANCH}", "sha": sha})
    except RuntimeError:
        pass  # raced with a concurrent create — fine


def attach_image_to_issue(number: int, image_path: str, caption: str = "",
                          repo: str | None = None, token: str | None = None) -> dict:
    """Upload a validation screenshot and post it as an INLINE image comment on the issue.

    The PNG is committed to the `evolve-evidence` branch (NOT main/release, so binaries don't bloat the
    code branches) and linked by its raw download URL so GitHub renders it in the comment. Requires a
    token with contents:write (the same PAT that files issues). Give each screenshot a UNIQUE filename
    per attempt (e.g. `ev42-medical-try2.png`) so a re-validation ADDS a new image instead of colliding
    with a prior one. Returns the created comment.
    """
    token = token or _token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    r = _repo(repo)
    _ensure_evidence_branch(token, r)
    with open(image_path, "rb") as fh:
        content = base64.b64encode(fh.read()).decode()
    name = os.path.basename(image_path)
    path = f"evidence/issue-{number}/{name}"
    try:
        put = _request("PUT", f"/repos/{r}/contents/{urllib.parse.quote(path)}", token, {
            "message": f"evidence: issue #{number} — {name}",
            "content": content,
            "branch": EVIDENCE_BRANCH,
        })
    except RuntimeError as e:
        if "403" in str(e):
            raise RuntimeError(
                "attach_image_to_issue needs a GitHub token with contents:write on the repo (the "
                "evidence is committed to the evolve-evidence branch). The current GITHUB_TOKEN only "
                "has issues:write — add Contents:Read+Write to the fine-grained PAT to enable evidence "
                "attachment.") from e
        raise
    raw_url = put["content"]["download_url"]
    blob_url = f"https://github.com/{r}/blob/{EVIDENCE_BRANCH}/{urllib.parse.quote(path)}"
    # Inline ![](raw) images only render on a PUBLIC repo. On a PRIVATE repo the raw.githubusercontent
    # URL 404s for any viewer (even GitHub's own image proxy can't auth to it), so link to the rendered
    # blob view instead — an authenticated viewer sees the image there. Auto-switches to inline once the
    # repo goes public.
    private = bool(_request("GET", f"/repos/{r}", token).get("private", True))
    if private:
        body = f"**Validation evidence** — {caption or name}\n\n[📷 View screenshot]({blob_url})"
    else:
        body = f"**Validation evidence** — {caption or name}\n\n![{caption or name}]({raw_url})"
    return post_comment(number, body, repo=r, token=token)


def create_issue(title: str, body: str = "", labels: list[str] | None = None,
                 repo: str | None = None, token: str | None = None) -> dict:
    """Open a NEW issue — used by Evolve to log a separate, INDEPENDENT bug an agent found while
    working a different item (so it enters the queue and gets triaged on its own merits, instead of
    being silently clubbed into an unrelated fix or lost in a gate note). Write-boundary: requires a
    token with Issues:write. NOT for coupled/blocking findings — those route to re-spec/Gate-1 so the
    operator approves the larger scope (see the loop's build segment + implement.md)."""
    token = token or _token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return _request("POST", f"/repos/{_repo(repo)}/issues", token, payload)


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
