# Third Party Notices

Skipperbot depends on a number of third-party open source libraries and tools.
This file exists to acknowledge those dependencies and to serve as the place
where any required third-party license notices are aggregated.

## Python dependencies

The Python runtime dependencies are declared in `requirements.txt`.
They include, but are not limited to:

- fastapi
- uvicorn
- pydantic
- python-multipart
- bcrypt
- python-dotenv
- psycopg2-binary
- pip-system-certs
- openai
- fastmcp
- mcp
- requests
- httpx
- beautifulsoup4
- discord.py
- resend
- google-auth
- google-auth-oauthlib
- google-api-python-client
- cryptography
- websockets
- pymupdf
- psutil
- croniter
- python-dateutil
- tzdata
- weasyprint
- markdown
- pyyaml
- prettytable
- diff-match-patch

## Web UI / JavaScript dependencies

The web frontend dependencies are declared in `web/package.json`.
They include, but are not limited to:

- @codemirror/autocomplete
- @codemirror/commands
- @codemirror/lang-markdown
- @codemirror/language
- @codemirror/language-data
- @codemirror/lint
- @codemirror/search
- @codemirror/state
- @codemirror/view
- @lezer/highlight
- @xterm/addon-fit
- @xterm/xterm
- @xyflow/react
- codemirror
- dagre
- diff-match-patch
- hls.js
- lucide-react
- react
- react-dom
- react-markdown
- recharts
- rehype-highlight
- remark-gfm
- three
- @tailwindcss/vite
- @vitejs/plugin-react
- tailwindcss
- vite
- vite-plugin-pwa

## License notice guidance

This project is licensed under the MIT License. Third-party packages may
use different licenses, and you are responsible for complying with the terms
of those packages when distributing or modifying Skipperbot.

For a complete and current list of third-party licenses, generate the list from
package metadata:

- Python: `pip-licenses --from=mixed --format=markdown`
- Node: `npx license-checker --json > third_party_licenses.json`

If any dependency requires a bundled license notice, add the specific text
from that dependency to this file.
