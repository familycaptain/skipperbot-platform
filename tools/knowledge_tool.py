"""
Knowledge Base Tools - Ingest, search, and manage knowledge from web sources.
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Ensure app root is on path so we can import knowledge_store
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from app_platform.memory import digest_record
from knowledge_store import (
    ingest_url, search_knowledge, list_sources, remove_source,
    create_crawl_manifest, list_crawls, get_crawl, format_crawl_manifest,
)


def learn_from_url(url: str, name: str = "", follow_links: bool = False) -> str:
    """Fetch a web page, extract its content, and store it in the knowledge base for future reference.

    Use this when a user asks you to read, learn, or ingest content from a URL.
    The content is chunked and embedded for semantic search.

    If follow_links is True, also ingests same-domain links found on the page.
    Only set follow_links=True if the user explicitly asks to crawl/read an entire
    site or wiki. When in doubt, ask the user first.

    When follow_links=True, a crawl manifest (kc-*) is automatically created grouping
    all ingested sources. Use list_knowledge_crawls to see manifests. The manifest
    can be attached to a project as an artifact.

    Args:
        url: The URL to fetch and ingest.
        name: Optional human-readable name for this source, e.g. "Bob's Project Wiki"
        follow_links: If True, also ingest same-domain links found on the page. Default False.

    Returns:
        Summary of what was ingested including chunk count and any links found.
    """
    try:
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"

        result = ingest_url(url, source_name=name if name else None)

        if "error" in result:
            return f"Error: {result['error']}"

        try:
            digest_record("knowledge", "knowledge source", "created", result["source_id"],
                          {"id": result["source_id"], "title": result.get("title", ""), "url": result.get("url", url)}, by="")
        except Exception:
            pass
        lines = [
            f"Ingested: {result['title']}",
            f"Source ID: {result['source_id']}",
            f"URL: {result['url']}",
            f"Chunks stored: {result['chunk_count']}",
        ]

        if follow_links and result.get("links"):
            lines.append(f"\nFollowing {len(result['links'])} same-domain links...")
            all_source_ids = [result["source_id"]]
            total_chunks = result["chunk_count"]
            success_count = 1  # count the root page
            fail_count = 0
            for link_url in result["links"]:
                try:
                    link_result = ingest_url(link_url, source_name=f"{result['title']} - subpage")
                    if "error" not in link_result:
                        success_count += 1
                        total_chunks += link_result["chunk_count"]
                        all_source_ids.append(link_result["source_id"])
                        lines.append(f"  + {link_url} ({link_result['chunk_count']} chunks)")
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1
            lines.append(f"\nCrawl complete: {success_count} pages ingested, {fail_count} failed")

            # Auto-create crawl manifest
            crawl_name = name if name else result["title"]
            manifest = create_crawl_manifest(
                root_url=url,
                name=crawl_name,
                source_ids=all_source_ids,
                pages_crawled=success_count,
                pages_failed=fail_count,
                total_chunks=total_chunks,
            )
            lines.append(f"\nCrawl manifest: {manifest['id']}")
            lines.append(f"To attach this crawl to a project: call get_knowledge_crawl(\"{manifest['id']}\") for the full manifest content, then use attach_artifact with that content. This ensures the artifact references the crawl ID and all {success_count} pages.")
            lines.append(f"If an artifact for this crawl already exists on the project, use update_artifact instead of creating a duplicate.")

            # Backfill crawl_id on all sources
            sources_list = list_sources()
            from knowledge_store import _write_sources
            updated = False
            for src in sources_list:
                if src["id"] in all_source_ids and not src.get("crawl_id"):
                    src["crawl_id"] = manifest["id"]
                    updated = True
            if updated:
                _write_sources(sources_list)

        elif result.get("links"):
            lines.append(f"\nFound {len(result['links'])} links on this page.")
            lines.append("Use follow_links=True to also ingest those pages, or ask the user.")

        return "\n".join(lines)
    except Exception as e:
        return f"Error ingesting URL: {str(e)}"


def query_knowledge(query: str, max_results: int = 5) -> str:
    """Search the knowledge base for information relevant to a query.

    Use this to find previously ingested content that may answer a user's question
    about topics covered by ingested sources.

    Args:
        query: Natural language search query, e.g. "how to deploy the app" or "API rate limits"
        max_results: Maximum number of relevant chunks to return. Default 5.

    Returns:
        Formatted list of relevant knowledge chunks with similarity scores.
    """
    try:
        results = search_knowledge(query, max_results=max_results)
        if not results:
            return "No relevant knowledge found. The knowledge base may be empty or the query didn't match any stored content."

        # Look up source names
        sources_list = list_sources()
        source_map = {s["id"]: s for s in sources_list}

        lines = [f"Found {len(results)} relevant chunks:"]
        for chunk in results:
            source = source_map.get(chunk["source_id"], {})
            source_name = source.get("name", "Unknown")
            source_url = source.get("url", "")
            sim_pct = f"{chunk['similarity'] * 100:.0f}%"
            lines.append(f"\n--- [{source_name}] (relevance: {sim_pct}) ---")
            if source_url:
                lines.append(f"Source: {source_url}")
            lines.append(chunk["text"][:1500])

        return "\n".join(lines)
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"


def list_knowledge_sources() -> str:
    """List all sources that have been ingested into the knowledge base.

    Returns:
        Formatted list of all ingested sources with their IDs, names, URLs, and chunk counts.
    """
    try:
        sources = list_sources()
        if not sources:
            return "The knowledge base is empty. No sources have been ingested yet."

        lines = [f"Knowledge base has {len(sources)} sources:"]
        for src in sources:
            date = src.get("ingested_at", "")[:10]
            lines.append(f"- [{src['id']}] {src['name']} ({src['chunk_count']} chunks) — {src['url']} [{date}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing sources: {str(e)}"


def remove_knowledge_source(source_id: str) -> str:
    """Remove a source and all its chunks from the knowledge base.

    Use this when a user asks to remove or forget a previously ingested source.
    Use list_knowledge_sources first to find the source ID.

    Args:
        source_id: The ID of the source to remove (from list_knowledge_sources).

    Returns:
        Confirmation that the source was removed, or an error if not found.
    """
    try:
        if not source_id.strip():
            return "Error: source_id cannot be empty."
        sources = list_sources()
        record = next((s for s in sources if s["id"] == source_id.strip()), {"id": source_id.strip()})
        removed = remove_source(source_id.strip())
        if removed:
            try:
                digest_record("knowledge", "knowledge source", "deleted", source_id.strip(), record, by="")
            except Exception:
                pass
            return f"Source {source_id} and all its chunks have been removed from the knowledge base."
        else:
            return f"No source found with id: {source_id}"
    except Exception as e:
        return f"Error removing source: {str(e)}"


def list_knowledge_crawls() -> str:
    """List all crawl manifests. A crawl manifest groups knowledge sources that
    were ingested together from a single site crawl (follow_links=true).

    Each manifest has a kc-* ID, root URL, page count, and list of source IDs.
    Use get_knowledge_crawl to see full details for a specific crawl.

    Returns:
        Formatted list of all crawl manifests.
    """
    try:
        crawls = list_crawls()
        if not crawls:
            return "No crawl manifests found. Crawl manifests are created automatically when learn_from_url is called with follow_links=True."

        lines = [f"Knowledge crawls ({len(crawls)}):"]
        for c in crawls:
            date = c.get("crawled_at", "")[:10]
            lines.append(
                f"- [{c['id']}] {c['name']} — {c['pages_crawled']} pages, "
                f"{c['total_chunks']} chunks from {c['root_url']} [{date}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing crawls: {str(e)}"


def get_knowledge_crawl(crawl_id: str) -> str:
    """Get full details of a crawl manifest including all source IDs and URLs.

    Use this to see what pages were ingested in a crawl. The output is formatted
    as markdown and can be used directly as artifact content when attaching a
    crawl to a project.

    Args:
        crawl_id: The crawl manifest ID (kc-*).

    Returns:
        Formatted markdown summary of the crawl, or error if not found.
    """
    try:
        manifest = get_crawl(crawl_id.strip())
        if not manifest:
            return f"No crawl manifest found with id: {crawl_id}"
        return format_crawl_manifest(manifest)
    except Exception as e:
        return f"Error retrieving crawl: {str(e)}"
