# Web & Network Tools Guide

## internet_search

Use `internet_search` when the user asks to search the web, look something up, or find information online. This calls the Brave Search API and returns title/URL/snippet results.

- **Does NOT ingest content** — it only returns search snippets. If the user wants to read a full page, use `learn_from_url` from the knowledge tools.
- Default: 5 results. Max: 10.
- Requires `BRAVE_API_KEY` in `.env`.

### When to use
- "Search for the best HVAC systems" → `internet_search(query="best HVAC systems")`
- "Find info about Python 3.13 changes" → `internet_search(query="Python 3.13 new features")`
- "Look up the weather in Dallas" → use the dedicated weather tools/category, not internet search

### When NOT to use
- If the user wants to read/ingest a specific URL → use `learn_from_url`
- If the user is asking about something already in knowledge base → use `query_knowledge`

## curl_request

Low-level HTTP tool for making direct API calls or fetching raw content.

- Use for REST API calls, webhooks, or fetching JSON/XML data
- For general web pages the user wants to learn from, prefer `learn_from_url`

## ping_host

Simple network connectivity check. Use when the user asks if a host/server is reachable.

## git_tool

Runs sandboxed Git operations. Two allowed zones:

### Zone 1: Application root (skipperbot)
- `repo_path="."` (the default) targets the skipperbot repo itself
- Use this for checking status, viewing diffs, committing changes to skipperbot
- **NEVER clone into this zone** — skipperbot is already a repo

### Zone 2: REPOS_BASE_DIR (external repos)
- `repo_path="<repo_name>"` targets a repo under `REPOS_BASE_DIR` (configured in `.env`)
- All clone operations go here automatically
- Use for working on any external/user repos

### Clone workflow
1. `git_tool(repo_path="my-project", operation="clone", args="https://github.com/user/repo.git", allow_network=True)`
2. This clones into `REPOS_BASE_DIR/my-project`
3. Subsequent operations: `git_tool(repo_path="my-project", operation="status")`

### Allowed operations
`status`, `diff`, `log`, `branch`, `show`, `remote`, `checkout`, `add`, `commit`, `pull`, `push`, `fetch`, `clone`

### Network operations
`clone`, `pull`, `push`, `fetch` all require `allow_network=True`. Always ask the user for confirmation before running network operations — especially `push`.

### Blocked operations
Destructive commands are blocked: `reset --hard`, `clean`, `rebase`, `filter-branch`, `--force`, `--delete`, etc. This is intentional and cannot be overridden.

### Key rules
- **repo_path="."** = skipperbot app repo (already exists, already a git repo)
- **repo_path="anything-else"** = resolves under REPOS_BASE_DIR
- **Clone ALWAYS goes to REPOS_BASE_DIR** — never clone inside the app root
- **Never push without asking** — always confirm with the user first
- **Commit messages are required** — use the `message` parameter
- Path traversal (`..`) is blocked in args

### Common patterns
- Check app repo status: `git_tool()` (defaults work)
- View recent commits: `git_tool(operation="log", args="-5")`
- Clone a repo: `git_tool(repo_path="project-name", operation="clone", args="https://github.com/user/repo.git", allow_network=True)`
- Work on cloned repo: `git_tool(repo_path="project-name", operation="diff")`
- Commit to app: `git_tool(operation="add", args=".")` then `git_tool(operation="commit", message="fix: description")`
