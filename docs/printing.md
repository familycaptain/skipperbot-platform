# Printing

Skipper can print your documents and recipes to a real printer. The whole point
is that it works **headless and unattended**: you send a chat message from your
phone, Skipper runs a backend job (say, a research write-up), and it prints at
home — with nobody sitting at the machine and no print dialog to click.

That "no human at the keyboard" requirement is what shapes the design below, and
it's why setup is a little more deliberate than clicking *Print* in an app.

> **One-time setup.** Most people set this once (a single field in Settings) and
> never touch it again. Budget ~5 minutes. There's nothing to buy.

## What you get

- **Print from chat** — "print that document", "print the vacation-planning doc",
  "print 3 copies of that recipe". Works from any surface (web, Discord, voice).
- **Headless background printing** — printing runs as a backend job, so it works
  when the trigger came from your phone and the server is a Pi in a closet.

---

## How Skipper prints (the 30-second model)

Every print is a two-stage pipeline:

1. **Make a PDF** — your document's markdown → styled HTML → PDF.
2. **Send the PDF to the printer** — via one of three backends, chosen
   automatically from your **Default printer** setting.

The send step is the part that varies by operating system, so Skipper has three
headless backends and picks the right one:

| Backend | When it's used | Works on | Needs |
|---|---|---|---|
| **IPP** (network) | The Default printer is an `ipp://…` URL | **Any** OS, native **or** Docker | Nothing — built in |
| **CUPS** (`lpr`) | A local/named printer on a host that has CUPS | macOS & Linux **native** | CUPS (already present) |
| **Ghostscript** | A local printer on **native Windows** | Windows native | Ghostscript installed |

**The short version:** if your printer is on your network (almost all modern
home printers are), use **IPP** — it needs no setup beyond one URL and works the
same everywhere, including inside Docker. The other two backends exist for
printers physically plugged into the host.

> **Docker users:** the container does **not** include CUPS, so a printer must be
> reached over the network — i.e. use **IPP**. This is the recommended path anyway.

---

## Which setup is for you

| Your situation | Use | Jump to |
|---|---|---|
| A Wi-Fi / network printer (any host OS, native or Docker) | **IPP** | [Network printer](#network-printer-ipp--recommended) |
| Printer plugged into a **macOS or Linux** host (native) | **CUPS** | [Local printer on macOS / Linux](#local-printer-on-macos--linux-cups) |
| Printer plugged into a **native Windows** host | **Ghostscript** | [Local printer on Windows](#local-printer-on-windows-ghostscript) |

All of them are configured in **Settings → Integrations → Default printer** — never
in `.env`.

---

## Network printer (IPP) — recommended

This works on every OS and deployment (native or Docker) and needs no software
installed. You give Skipper the printer's IPP URL and you're done.

### 1. Find your printer's IPP URL

The standard form is:

```
ipp://<printer-ip-or-hostname>:631/ipp/print
```

- **Find the IP/hostname:** check the printer's control-panel network/status page,
  or your router's list of connected devices. The mDNS name usually works too —
  e.g. `ipp://Brother-HL.local:631/ipp/print`.
- **Path:** `/ipp/print` is the IPP Everywhere / AirPrint standard and is correct
  for the vast majority of printers. A few older models use a different path
  (e.g. `/ipp/printer`); if the standard one is rejected, check the printer's IPP
  settings page for its exact "ipp://" URI.
- **Already used this printer via CUPS once?** `lpstat -v` prints the device URI.
- **Secure printers:** `ipps://…` (TLS) is also accepted — Skipper tolerates the
  self-signed certificate printers ship with.

### 2. Enter it in Settings

1. Open the web UI → **Settings** → **Integrations**.
2. Put the IPP URL in **Default printer** and save.

That's it — no restart. The setting is read fresh on each print job.

---

## Local printer on macOS / Linux (CUPS)

If the printer is attached to (or already configured on) a **native** macOS or
Linux host, Skipper uses CUPS automatically — the same `lpr` your OS uses.

- **Leave Default printer blank** to use the host's default printer, **or**
- Enter the **CUPS queue name** (from `lpstat -p`) to target a specific one.

No extra install — CUPS ships with macOS and is standard on Linux. (Reminder:
this path is **not** available inside Docker; use IPP there.)

---

## Local printer on Windows (Ghostscript)

Native Windows has no CUPS. For a printer **plugged into a Windows host**, Skipper
prints through the Windows spooler using **Ghostscript** — fully headless, works
under a service account.

> If your Windows printer is on the network, prefer **IPP** above — it needs no
> install. Use this section only for a USB/local printer.

1. **Install Ghostscript** — the AGPL build from
   [ghostscript.com/releases](https://ghostscript.com/releases/index.html).
   Skipper finds `gswin64c.exe` on `PATH` or in `C:\Program Files\gs\…`.
2. In **Settings → Integrations → Default printer**, either leave it **blank**
   (uses your Windows default printer) or enter the **exact Windows printer name**
   (as shown in *Settings → Bluetooth & devices → Printers & scanners*).

If Ghostscript isn't installed, a print attempt fails with a clear message
telling you to install it or use a network (IPP) printer instead.

---

## The PDF step (all platforms)

Before sending anything, Skipper renders your document to a PDF. It tries, in
order: **WeasyPrint** → **headless Chrome/Chromium/Edge** → **wkhtmltopdf** →
**pandoc**, and uses the first that works.

- **Docker & native macOS/Linux:** WeasyPrint ships with the platform (its system
  libraries are in the Docker image and its Python package is a pinned
  dependency), so PDF generation works out of the box.
- **Native Windows:** WeasyPrint needs extra GTK libraries that are awkward to
  install, so Skipper falls back to **Microsoft Edge** in headless mode. Edge is
  on every Windows machine and is Chromium-based, so this needs **no install**.

You normally don't have to think about this stage — it just works on every
supported setup.

---

## Verify

Ask Skipper to print something you have:

```
print that document
```

or, in the web UI, open a document and use its print action. A print job appears
in the **Jobs** view; on success you get a "Printed!" notification naming the
method used (e.g. *via IPP*, *via Ghostscript*). The page comes out of your
printer.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "No printing method available on this host" | No printer configured and no CUPS present (e.g. Docker or native Windows). Set an **IPP URL** in Settings → Integrations → Default printer. |
| "Could not reach printer at http://…" | Wrong IP/hostname, printer asleep/off, or it's on a different VLAN/subnet than the server. Confirm the server can reach the printer's IP, and that the IPP URL (host **and** path) is right. |
| "Printer rejected the job (IPP status 0x…)" | The printer doesn't accept PDF directly, or the path is wrong. Try the printer's exact IPP URI; for a non-PDF (raster-only) printer, print from a macOS/Linux host via **CUPS** instead, which converts the format. |
| Windows: "install Ghostscript…" | The Ghostscript backend ran but `gswin64c.exe` isn't installed/found. Install it, or use an IPP network printer. |
| Windows: "No Windows printer found" | No default printer set and none named. Set a default in Windows, or put the exact printer name in Settings. |
| "No PDF converter available" | The PDF stage failed. On native Windows, ensure Microsoft Edge is present (it is by default); on Linux/macOS, WeasyPrint ships with the platform — reinstall dependencies if it was stripped. |
| Prints the wrong number of copies | Copies are clamped to 1–10. Some printers ignore the IPP `copies` attribute; if so, the count is honored by the spooler/CUPS path instead. |

---

## How it works (for the curious)

- **Pipeline + PDF stage:** `print_runner.py` (`_run_print_pipeline`, `_html_to_pdf`).
- **Backends + dispatcher:** `print_backends.py` — `print_pdf(pdf, copies, printer)`
  routes to the IPP, CUPS, or Windows-spooler backend. The IPP client is a minimal
  pure-Python `Print-Job` request (no external print stack).
- **Tool the model calls:** `tools/print_tool.py` (`print_doc`, `print_recipe`),
  which queues a background `print` job via the Jobs app.
- **Setting:** `default_printer` (scope `platform`), declared in
  `apps/settings/routes.py` and surfaced in the Integrations panel.

## Limitations

- **Raster-only network printers.** A small number of cheap printers don't accept
  PDF over IPP (they want PWG-Raster). For those, print from a macOS/Linux host via
  CUPS, which does the conversion, or attach them to such a host.
- **Native-Windows local printers need Ghostscript.** It's a one-time install; a
  network printer over IPP avoids it entirely.
- **Printer discovery is manual.** Skipper doesn't auto-scan the network for
  printers — you provide the IPP URL (or rely on the OS default queue). This keeps
  the feature dependency-light and predictable across very different home networks.
