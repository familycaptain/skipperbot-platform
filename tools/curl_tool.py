"""curl_tool

A sandboxed HTTP client tool (curl-like) for fetching pages, posting data, and optionally
saving downloads into a tmp folder within the app.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()

import json
import re
import socket
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple


def curl_request(
    url: str,
    method: str = "GET",
    headers_json: str = "{}",
    data: str = "",
    timeout_seconds: int = 30,
    follow_redirects: bool = True,
    save_to_tmp: bool = False,
    tmp_filename: str = "",
    max_response_bytes: int = 2_000_000,
) -> str:
    """Make an HTTP request (GET/POST/etc), scrape text/HTML, and optionally download to tmp.

    This is a safe, curl-like HTTP client limited to http(s) URLs. It can fetch HTML for scraping,
    send POST bodies, and optionally save binary responses to a tmp folder inside the application.

    Args:
        url: The http(s) URL to request.
        method: HTTP method (e.g., GET, POST, PUT, PATCH, DELETE, HEAD).
        headers_json: Request headers as a JSON object string (e.g., '{"Accept":"text/html"}').
        data: Request body as a string. If it parses as JSON, Content-Type defaults to application/json
            (unless provided in headers). Otherwise defaults to application/x-www-form-urlencoded when method
            typically carries a body.
        timeout_seconds: Socket timeout in seconds.
        follow_redirects: Whether to follow redirects.
        save_to_tmp: If true, saves response body to app/tmp/<tmp_filename or derived name>.
        tmp_filename: Optional filename to use when saving into tmp. Must be a simple filename (no paths).
        max_response_bytes: Maximum bytes to read into memory when not saving to tmp.

    Returns:
        A formatted string with status, headers, and either a text preview/body or the saved filepath.
    """

    app_root = os.getcwd()
    tmp_dir = os.path.join(app_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # --- Validate URL ---
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return f"Error: invalid URL ({e})"

    if parsed.scheme not in ("http", "https"):
        return "Error: only http/https URLs are allowed"

    if not parsed.netloc:
        return "Error: URL must include a hostname"

    hostname = parsed.hostname or ""

    # --- Resolve DNS and screen destination addresses ---
    # Operator policy (deliberate): internal / home-lab destinations — localhost,
    # RFC-1918 (10/8, 172.16/12, 192.168/16), CGNAT, link-local, IPv6 ULA — ARE
    # allowed, so Skipper apps can reach locally-hosted APIs on the home network.
    # Only the cloud instance-metadata endpoints are blocked: never a legitimate
    # home-lab target, and the classic SSRF credential-theft target on cloud.
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
        ips = sorted({ai[4][0] for ai in addrinfos})
    except Exception as e:
        return f"Error: could not resolve host '{hostname}' ({e})"

    _METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}

    def _is_blocked_ip(ip: str) -> bool:
        return ip.lower() in _METADATA_IPS

    blocked = [ip for ip in ips if _is_blocked_ip(ip)]
    if blocked:
        return f"Error: blocked destination (cloud metadata endpoint: {', '.join(blocked)})"

    # --- Parse headers ---
    try:
        headers_obj = json.loads(headers_json) if headers_json.strip() else {}
        if not isinstance(headers_obj, dict):
            return "Error: headers_json must be a JSON object"
        # normalize to str:str
        headers: Dict[str, str] = {str(k): str(v) for k, v in headers_obj.items()}
    except Exception as e:
        return f"Error: could not parse headers_json ({e})"

    # default UA
    headers.setdefault("User-Agent", "SkipperBot/1.0 (curl_tool)")

    method_u = (method or "GET").upper().strip()

    # --- Prepare body ---
    body_bytes: Optional[bytes] = None
    if data and method_u in ("POST", "PUT", "PATCH", "DELETE"):
        ct_key = None
        for k in headers.keys():
            if k.lower() == "content-type":
                ct_key = k
                break

        # if data looks like JSON, default to json
        is_json = False
        try:
            json.loads(data)
            is_json = True
        except Exception:
            is_json = False

        if ct_key is None:
            headers["Content-Type"] = "application/json" if is_json else "application/x-www-form-urlencoded"

        body_bytes = data.encode("utf-8")
        headers.setdefault("Content-Length", str(len(body_bytes)))

    # --- Redirect handling ---
    handlers = []
    if not follow_redirects:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None
        handlers.append(_NoRedirect())

    opener = urllib.request.build_opener(*handlers)

    req = urllib.request.Request(url=url, data=body_bytes, method=method_u)
    for k, v in headers.items():
        req.add_header(k, v)

    # Ensure tmp dir exists if saving
    if save_to_tmp:
        os.makedirs(tmp_dir, exist_ok=True)

    def _sanitize_filename(name: str) -> str:
        # only allow a simple filename, no directories
        name = name.strip().replace("\\", "/")
        if "/" in name or name in (".", ".."):
            return ""
        # remove weird chars
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return name

    def _derive_filename(resp_headers) -> str:
        cd = resp_headers.get("Content-Disposition", "")
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
        if m:
            return urllib.parse.unquote(m.group(1))
        m = re.search(r"filename=\"?([^\";]+)\"?", cd)
        if m:
            return m.group(1)
        # fallback to path basename
        p = urllib.parse.urlparse(url).path
        base = os.path.basename(p) if p else ""
        return base or "download.bin"

    try:
        with opener.open(req, timeout=timeout_seconds) as resp:
            status = getattr(resp, "status", None)
            reason = getattr(resp, "reason", "")
            resp_headers = resp.headers
            content_type = resp_headers.get("Content-Type", "")

            if save_to_tmp:
                fn = _sanitize_filename(tmp_filename) if tmp_filename else ""
                if not fn:
                    fn = _sanitize_filename(_derive_filename(resp_headers)) or "download.bin"

                out_path = os.path.join(tmp_dir, fn)
                out_path_abs = os.path.abspath(out_path)
                if not out_path_abs.startswith(os.path.abspath(tmp_dir) + os.sep) and out_path_abs != os.path.abspath(tmp_dir):
                    return "Error: invalid tmp filename"

                # stream to disk
                total = 0
                with open(out_path, "wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
                        # hard cap to prevent huge downloads
                        if total > max(10_000_000, max_response_bytes):
                            return f"Error: download exceeded limit ({total} bytes)"

                return (
                    f"{method_u} {url}\n"
                    f"Status: {status} {reason}\n"
                    f"Content-Type: {content_type}\n"
                    f"Saved: tmp/{fn} ({total} bytes)"
                )

            # else read into memory with cap
            raw = resp.read(max_response_bytes + 1)
            truncated = len(raw) > max_response_bytes
            if truncated:
                raw = raw[:max_response_bytes]

            # decode best-effort for scraping
            text = ""
            if method_u == "HEAD":
                text = ""
            else:
                charset = "utf-8"
                m = re.search(r"charset=([^;]+)", content_type, re.IGNORECASE)
                if m:
                    charset = m.group(1).strip()
                try:
                    text = raw.decode(charset, errors="replace")
                except Exception:
                    text = raw.decode("utf-8", errors="replace")

            # format headers succinctly
            hdr_lines = []
            for k, v in resp_headers.items():
                hdr_lines.append(f"{k}: {v}")
            hdr_out = "\n".join(hdr_lines)

            body_out = text
            if len(body_out) > 8000:
                body_out = body_out[:8000] + "\n...[truncated preview]"

            trunc_note = "\nNote: response truncated to max_response_bytes" if truncated else ""

            return (
                f"{method_u} {url}\n"
                f"Status: {status} {reason}\n"
                f"Resolved IPs: {', '.join(ips)}\n"
                f"--- Response Headers ---\n{hdr_out}\n"
                f"--- Body Preview ---\n{body_out}{trunc_note}"
            )

    except urllib.error.HTTPError as e:
        # HTTP status errors still have bodies sometimes
        try:
            err_body = e.read(4096).decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return (
            f"{method_u} {url}\n"
            f"HTTPError: {e.code} {e.reason}\n"
            f"Body (first 4KB):\n{err_body}"
        )
    except Exception as e:
        return f"Error: request failed ({type(e).__name__}: {e})"
