"""Print backends — pluggable, headless, cross-platform.

The platform must print the same way for every self-hosted user: macOS / Linux /
Windows, native or Docker, to a local or network printer, with NO desktop session
(a print job is usually kicked off remotely — e.g. a phone chat message spawns a
backend research job that then prints at home). See specs and MEMORY.

Two backends, selected per job by the configured printer (Settings → Integrations →
"Default printer"):

  * **IPP** (the universal default): when the printer is an ``ipp://``/``ipps://``
    URL, send the PDF straight to the printer over the network using a minimal
    Internet Printing Protocol ``Print-Job`` request. Pure Python (``requests`` +
    stdlib) — no CUPS, no spooler, no drivers, no GUI. Works identically on every
    OS and deploy mode. This is how AirPrint/IPP-Everywhere printers accept jobs.

  * **CUPS** (``lpr``): the fallback when no IPP URL is configured. Auto-available
    on macOS / Linux / Docker; also handles locally-attached printers and the
    driver/raster conversion that cheap non-PDF printers need. Not present on
    native Windows.

Public API: ``print_pdf(pdf_path, copies, printer)`` and ``list_printers()``.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import struct
import subprocess
import sys
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IPP backend (network printers, any OS) — minimal Print-Job over HTTP
# ---------------------------------------------------------------------------

# IPP tag/operation constants (RFC 8010/8011).
_IPP_VERSION = b"\x02\x00"            # IPP 2.0
_OP_PRINT_JOB = b"\x00\x02"
_TAG_OPERATION_ATTRS = b"\x01"
_TAG_JOB_ATTRS = b"\x02"
_TAG_END = b"\x03"
_VT_INTEGER = 0x21
_VT_CHARSET = 0x47
_VT_NATURAL_LANG = 0x48
_VT_URI = 0x45
_VT_NAME = 0x42                       # nameWithoutLanguage
_VT_MIME = 0x49                       # mimeMediaType


def _ipp_attr(value_tag: int, name: str, value: bytes) -> bytes:
    """Encode one IPP attribute: tag, name (len-prefixed), value (len-prefixed)."""
    nb = name.encode("utf-8")
    return (bytes([value_tag])
            + struct.pack(">H", len(nb)) + nb
            + struct.pack(">H", len(value)) + value)


def is_ipp_target(printer: str) -> bool:
    return (printer or "").strip().lower().startswith(("ipp://", "ipps://"))


def _ipp_http_endpoint(printer_uri: str) -> tuple[str, bool]:
    """Map an ipp(s):// printer URI to the HTTP(S) URL to POST to.

    IPP rides on HTTP. ``ipp`` → ``http``, ``ipps`` → ``https`` (TLS, usually a
    self-signed printer cert). The default IPP port is 631 — force it when the URI
    omits one (otherwise http would default to 80 and miss the printer). Returns
    (url, is_tls).
    """
    parts = urlsplit(printer_uri)
    is_tls = parts.scheme.lower() == "ipps"
    scheme = "https" if is_tls else "http"
    host = parts.hostname or "localhost"
    port = parts.port or 631
    path = parts.path or "/"
    return f"{scheme}://{host}:{port}{path}", is_tls


def _ipp_print_job(printer_uri: str, pdf_path: str, copies: int = 1,
                   user: str = "skipper", job_name: str = "Skipper") -> tuple[bool, str]:
    """Send a PDF to a network printer via an IPP Print-Job request."""
    try:
        import requests
    except ImportError:
        return False, "IPP printing needs the 'requests' package (it ships with the platform)."

    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
    except OSError as e:
        return False, f"Could not read PDF: {e}"

    # Build the IPP operation. printer-uri MUST be the ipp:// URI (not the http one).
    req = bytearray()
    req += _IPP_VERSION
    req += _OP_PRINT_JOB
    req += b"\x00\x00\x00\x01"                       # request-id = 1
    req += _TAG_OPERATION_ATTRS
    req += _ipp_attr(_VT_CHARSET, "attributes-charset", b"utf-8")
    req += _ipp_attr(_VT_NATURAL_LANG, "attributes-natural-language", b"en")
    req += _ipp_attr(_VT_URI, "printer-uri", printer_uri.encode("utf-8"))
    req += _ipp_attr(_VT_NAME, "requesting-user-name", user.encode("utf-8"))
    req += _ipp_attr(_VT_NAME, "job-name", job_name[:255].encode("utf-8"))
    req += _ipp_attr(_VT_MIME, "document-format", b"application/pdf")
    if copies and copies > 1:
        req += _TAG_JOB_ATTRS
        req += _ipp_attr(_VT_INTEGER, "copies", struct.pack(">i", int(copies)))
    req += _TAG_END
    req += pdf_bytes

    url, is_tls = _ipp_http_endpoint(printer_uri)
    try:
        # Printers ship self-signed certs, so don't verify TLS for ipps://.
        kwargs = {"verify": False} if is_tls else {}
        if is_tls:
            try:  # hush the one-time InsecureRequestWarning
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
        resp = requests.post(
            url, data=bytes(req),
            # Force identity encoding: many printers' embedded HTTP servers reject
            # the default "Accept-Encoding: gzip, deflate, br" with HTTP 406, since
            # IPP bodies are never compressed. Without this, real printers 406 us.
            headers={"Content-Type": "application/ipp", "Accept-Encoding": "identity"},
            timeout=60, **kwargs,
        )
    except Exception as e:
        return False, f"Could not reach printer at {url}: {e}"

    if resp.status_code != 200:
        return False, f"Printer returned HTTP {resp.status_code} (is the IPP URL correct?)"
    if len(resp.content) < 4:
        return False, "Printer gave an empty IPP response."

    # IPP response: version(2) + status-code(2) + ... ; success codes are < 0x0100.
    status = struct.unpack(">H", resp.content[2:4])[0]
    if status < 0x0100:
        cps = f"{copies} {'copy' if copies == 1 else 'copies'}"
        return True, f"Sent to {urlsplit(printer_uri).hostname} via IPP ({cps})"
    return False, f"Printer rejected the job (IPP status 0x{status:04x})."


# ---------------------------------------------------------------------------
# CUPS backend (lpr / lpstat) — macOS / Linux / Docker; local + raster printers
# ---------------------------------------------------------------------------

def _cups_available() -> bool:
    return bool(shutil.which("lpr"))


def _cups_list_printers() -> list[str]:
    """Discover CUPS queues via lpstat."""
    try:
        result = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=5)
        out = []
        for line in result.stdout.splitlines():
            if line.startswith("printer "):
                parts = line.split()
                if len(parts) >= 2:
                    out.append(parts[1])
        return out
    except Exception:
        return []


def _cups_print(pdf_path: str, copies: int = 1, printer: str = "") -> tuple[bool, str]:
    """Send a PDF to CUPS via lpr. Tries the named/default queue first, then
    auto-discovers and retries each available queue."""
    lpr = shutil.which("lpr")
    if not lpr:
        return False, "lpr not found — CUPS is not available on this host."

    def _try(name: str = "") -> tuple[bool, str]:
        cmd = [lpr]
        if name:
            cmd += ["-P", name]
        if copies > 1:
            cmd += ["-#", str(copies)]
        cmd.append(pdf_path)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                dest = name or "default printer"
                return True, f"Sent to {dest} ({copies} {'copy' if copies == 1 else 'copies'})"
            return False, (r.stderr.strip() or r.stdout.strip() or "unknown lpr error")
        except Exception as e:
            return False, str(e)

    ok, msg = _try(printer)
    if ok:
        return True, msg
    if printer:
        # An explicit queue was named and failed — don't silently print elsewhere.
        return False, f"lpr failed for '{printer}': {msg}"

    logger.warning("PRINT: default lpr failed: %s — trying discovered printers", msg)
    printers = _cups_list_printers()
    if not printers:
        return False, f"lpr failed: {msg} (no other printers found)"
    for p in printers:
        ok, retry = _try(p)
        if ok:
            return True, retry
    return False, f"lpr failed: {msg} (also tried: {', '.join(printers)})"


# ---------------------------------------------------------------------------
# Windows spooler backend (Ghostscript) — native Windows, local/USB printers
# ---------------------------------------------------------------------------
# For a network printer, IPP (above) already works on Windows with no install.
# This covers the remaining case: a printer attached to a *native* Windows host
# with no CUPS. Ghostscript's ``mswinpr2`` device prints a PDF straight through
# the Windows spooler — fully headless, no GUI, works under a service account.

def _ghostscript_exe() -> str:
    """Locate the Ghostscript console binary on Windows (gswin64c/gswin32c)."""
    for cand in ("gswin64c", "gswin32c"):
        p = shutil.which(cand)
        if p:
            return p
    for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")):
        if not base:
            continue
        # e.g. C:\Program Files\gs\gs10.03.0\bin\gswin64c.exe — prefer newest.
        hits = glob.glob(os.path.join(base, "gs", "gs*", "bin", "gswin*c.exe"))
        for exe in sorted(hits, reverse=True):
            if os.path.exists(exe):
                return exe
    return ""


def _powershell(cmd: str) -> str:
    """Run a one-liner via PowerShell and return stdout (empty on any failure)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _windows_default_printer() -> str:
    return _powershell("(Get-CimInstance Win32_Printer -Filter 'Default=True').Name")


def _windows_list_printers() -> list[str]:
    out = _powershell("Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _windows_spooler_print(pdf_path: str, copies: int = 1, printer: str = "") -> tuple[bool, str]:
    """Print a PDF to a Windows printer via Ghostscript's mswinpr2 device."""
    gs = _ghostscript_exe()
    if not gs:
        return False, (
            "To print to a printer attached to this Windows PC, install Ghostscript "
            "(https://ghostscript.com/releases/) — or point Skipper at a network "
            "printer's IPP URL in Settings, which needs no install."
        )
    name = (printer or "").strip() or _windows_default_printer()
    if not name:
        return False, ("No Windows printer found. Set one as the default in Windows, "
                       "or enter its name in Settings → Integrations → Default printer.")
    # mswinpr2 REQUIRES a named printer (`%printer%<name>`); without it Ghostscript
    # would pop a selection dialog — not headless. NumCopies is honored by the device.
    cmd = [
        gs, "-dPrinted", "-dBATCH", "-dNOPAUSE", "-dQUIET",
        f"-dNumCopies={int(copies)}",
        "-sDEVICE=mswinpr2", f"-sOutputFile=%printer%{name}",
        pdf_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            cps = f"{copies} {'copy' if copies == 1 else 'copies'}"
            return True, f"Sent to {name} via Ghostscript ({cps})"
        return False, (r.stderr.strip() or r.stdout.strip() or "Ghostscript print error")
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def print_pdf(pdf_path: str, copies: int = 1, printer: str = "") -> tuple[bool, str]:
    """Send a PDF to the printer, choosing a backend from ``printer``.

    * ``ipp://…`` / ``ipps://…``  → IPP (network, OS-independent, headless).
    * a CUPS queue name or ``""`` → CUPS/lpr (the named queue, or the default).

    Returns (success, human_message).
    """
    printer = (printer or "").strip()
    copies = max(1, int(copies or 1))

    if is_ipp_target(printer):
        return _ipp_print_job(printer, pdf_path, copies)

    if _cups_available():
        return _cups_print(pdf_path, copies, printer)

    if sys.platform == "win32":
        # Native Windows, no CUPS: print a local printer via Ghostscript.
        return _windows_spooler_print(pdf_path, copies, printer)

    return False, (
        "No printing method available on this host. Set a network printer URL "
        "(e.g. ipp://printer.local:631/ipp/print) in Settings → Integrations → "
        "\"Default printer\", or run on a host with CUPS (lpr) installed."
    )


def list_printers() -> list[str]:
    """Best-effort list of local printer queues. (IPP printers are addressed by
    URL, not name, so they don't appear here.)"""
    if _cups_available():
        return _cups_list_printers()
    if sys.platform == "win32":
        return _windows_list_printers()
    return []
