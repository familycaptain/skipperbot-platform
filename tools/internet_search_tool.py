import os
from dotenv import load_dotenv
load_dotenv()

import json
import urllib.request
import urllib.parse


def internet_search(query: str, num_results: int = 5) -> str:
    """Search the public internet using the Brave Search API.

    Use this tool when the user asks to search the internet/net/web or look something up.
    This does NOT ingest results into knowledge; it only returns search snippets.

    Args:
        query: The search query string.
        num_results: Number of results to return (1-10). Defaults to 5.

    Returns:
        A formatted list of search results (title, URL, snippet) or an error message.

    Ack: Searching the web for "{query}"...
    """
    try:
        from app_platform import settings as _settings
        api_key = _settings.get("brave_api_key", scope="platform", secret=True, default="")
        if not api_key:
            return "Error: BRAVE_API_KEY is not set in the .env file."

        try:
            n = int(num_results)
        except Exception:
            n = 5
        n = max(1, min(10, n))

        base_url = "https://api.search.brave.com/res/v1/web/search"
        params = {
            "q": query,
            "count": str(n),
            "safesearch": "moderate",
            "text_decorations": "false",
        }
        url = base_url + "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
                "User-Agent": "SkipperBot/1.0",
            },
            method="GET",
        )

        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        data = json.loads(raw)
        results = (data.get("web") or {}).get("results") or []

        if not results:
            return f"No results found for: {query}"

        lines = [f"Brave web search results for: {query}", ""]
        for i, r in enumerate(results[:n], start=1):
            title = (r.get("title") or "").strip() or "(no title)"
            link = (r.get("url") or "").strip() or "(no url)"
            snippet = (r.get("description") or "").strip() or ""
            lines.append(f"{i}. {title}\n   {link}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

        lines.append("Note: I only searched. If you want me to read a specific result, paste the URL and I can use learn_from_url.")
        return "\n".join(lines).strip()

    except Exception as e:
        return f"Error in internet_search: {str(e)}"
