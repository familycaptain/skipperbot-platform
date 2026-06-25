"""platform.location.resolver — the single shared home-location service.

This is PLATFORM CORE, not a weather concern. Apps (weather, voice, …) CONSUME
it; it must never import from ``apps/*`` (that would invert the layer). It owns:

  - the cached platform setting ``default_location`` (resolve, no per-request
    geocoding),
  - on-demand geocoding of an explicit override (a place name like
    "Lyon, France" or a "<postal>,<COUNTRY>" string),
  - the ONE canonical place-name formatter (``display_label``),
  - the geocode-and-store path used by Settings (``save_default_location``),
  - lazy migration of a legacy ``default_zip`` (US postal) → ``default_location``.

Geocoding uses Open-Meteo's geocoding API (no key). The default resolve path
performs NO geocoding: it returns the cached record (validated on read) and
fails safe. Home location (postal / place / lat / lon) is never logged at INFO
and never echoed into an error string returned to the agent/UI — details only
go to DEBUG.
"""

from __future__ import annotations

import collections
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_USER_AGENT = "SkipperBot/0.1"
_HTTP_TIMEOUT = 10

# A clear, location-free message shown when nothing is configured and no
# override is given. NEVER contains a user-supplied value.
NO_LOCATION_MSG = (
    "No location is configured. Set your home location in Settings → System → "
    '"Location" (e.g. "Austin, Texas, US" or "SW1A 1AA, UK"), or pass a place '
    "name / postal code with your request."
)

_SETTING_KEY = "default_location"
_LEGACY_ZIP_KEY = "default_zip"


# ---------------------------------------------------------------------------
# Errors. Their str() must NOT contain the home location — callers surface them.
# ---------------------------------------------------------------------------

class LocationError(Exception):
    """Base for location-service failures (message is location-free)."""


class LocationNotFound(LocationError):
    """The geocoder ran but found no match for the query."""


class GeocoderUnavailable(LocationError):
    """The geocoder was unreachable (offline / timeout / HTTP error) — transient."""


# ---------------------------------------------------------------------------
# Inline HTTPS helper — https-only, redirects DISABLED, hard timeout, fixed UA.
# Deliberately NOT importing weather's _fetch_json (that would invert the layer).
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # noqa: D401
        return None  # never follow redirects


_OPENER = urllib.request.build_opener(_NoRedirect())


def _http_get_json(url: str, *, timeout: int = _HTTP_TIMEOUT) -> dict:
    """GET ``url`` (https only, no redirects) and parse JSON.

    Raises GeocoderUnavailable on any transport/HTTP/parse failure. The raised
    message is generic; the URL (which may carry the home location) is logged
    only at DEBUG.
    """
    if not url.lower().startswith("https://"):
        raise GeocoderUnavailable("location service: refused non-https request")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # ValueError covers JSON decode; URLError covers timeout/offline/HTTP.
        logger.debug("location service: geocode request failed (%s): %s",
                     type(exc).__name__, url)
        raise GeocoderUnavailable("location service temporarily unavailable") from exc


# ---------------------------------------------------------------------------
# Query parsing + geocoding
# ---------------------------------------------------------------------------

# Map of the country tokens we accept against Open-Meteo's ISO-3166 country_code.
# Open-Meteo returns a 2-letter code; we also accept full names / common forms.
_COUNTRY_ALIASES = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "united states": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "great britain": "GB",
    "britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
}

# US-state abbreviation → full admin1 name (50 states + DC). A trailing 2-letter
# token that is one of these is a REGION hint, NOT an Open-Meteo countryCode —
# that mis-binding was the "Austin, TX" bug (TX was sent as countryCode=TX).
# Region matching is done client-side; non-US region abbreviations are out of
# scope (full admin1 names still match for any country).
_US_STATE_ABBR = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}


def _normalize_country(token: str) -> str | None:
    """Best-effort normalize a country token to an ISO-3166 alpha-2 code, or
    None if we can't tell. A bare 2-letter token is taken as a code."""
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[t]
    if len(t) == 2 and t.isalpha():
        return t.upper()
    return None


# What a parsed override yields. ``url_country`` is the ONLY value sent to
# Open-Meteo's server-side countryCode filter (so the original forms keep
# byte-for-byte identical URLs); ``region_hint`` / ``filter_code`` /
# ``filter_name`` are applied CLIENT-SIDE over the single result set.
_Parsed = collections.namedtuple(
    "_Parsed", ["search_name", "url_country", "region_hint", "filter_code", "filter_name"])


def _parse_query(query: str) -> "_Parsed":
    """Split a free-text override into geocode inputs.

    The FIRST comma-token is ALWAYS the city (Open-Meteo's ``name`` search
    term). Accepted forms (all strictly additive over the originals):
      - bare name .............. "Lyon"                       → name only
      - "City, Country" ........ "Chicago, US" / "Lyon, France"   (unchanged)
      - "<postal>,<country>" ... "SW1A 1AA, UK"               (unchanged)
      - "City, Region" ......... "Austin, TX" / "Austin, Texas"   (NEW, 2-piece)
      - "City, Region, Country"  "Austin, Texas, US" / "Austin, TX, US"  (NEW)

    Region/country preference is resolved CLIENT-SIDE so the geocode stays a
    single call. A trailing 2-letter US-state token is NEVER sent as
    ``url_country`` (the "Austin, TX" bug); for a token that is BOTH a US state
    and an ISO country (CA/IN/DE…) the state is kept as a region hint AND the
    code as a client-side country fallback → region-first-else-country. Blank
    comma-tokens (e.g. "Austin,,US" or a trailing comma) are ignored as absent
    hints."""
    q = (query or "").strip()
    if "," not in q:
        return _Parsed(q, None, None, None, None)

    parts = [p.strip() for p in q.split(",")]
    parts = [p for p in parts if p]            # ignore blank comma-tokens
    if not parts:
        return _Parsed("", None, None, None, None)
    if len(parts) == 1:
        return _Parsed(parts[0], None, None, None, None)

    city = parts[0]
    if len(parts) >= 3:
        # "City, …, Region, Country" — second-to-last is the region, last the country.
        region_tok, country_tok = parts[-2], parts[-1]
        cc = _normalize_country(country_tok)
        if cc:
            return _Parsed(city, cc, region_tok, cc, None)
        return _Parsed(city, None, region_tok, None, country_tok)

    # 2-piece "City, X" — X is a region OR a country, decided over the results.
    tok = parts[1]
    if tok.upper() in _US_STATE_ABBR:
        # US-state token: a REGION hint, NOT a server-side countryCode. Keep its
        # ISO reading (CA/IN/DE…) only as a CLIENT-SIDE country fallback.
        return _Parsed(city, None, tok, _normalize_country(tok), None)
    cc = _normalize_country(tok)
    if cc:
        # "Chicago, US" — country code (server-side, unchanged); also a (harmless)
        # region candidate so the 2-piece form stays region-OR-country.
        return _Parsed(city, cc, tok, cc, None)
    # "Lyon, France" — free text: try as a region, else as a country NAME (unchanged).
    return _Parsed(city, None, tok, None, tok)


def _matches_country(r: dict, code: str | None, hint: str | None) -> bool:
    if code:
        return str(r.get("country_code", "")).upper() == code
    if hint:
        return hint.strip().lower() == str(r.get("country", "")).strip().lower()
    return True


def _matches_region(r: dict, region_hint: str | None) -> bool:
    """True when a result's admin1 matches the region hint (case-insensitive),
    accepting a US-state abbreviation as its full admin1 name."""
    if not region_hint:
        return False
    admin1 = str(r.get("admin1") or "").strip().lower()
    if not admin1:
        return False
    h = region_hint.strip()
    if admin1 == h.lower():
        return True
    full = _US_STATE_ABBR.get(h.upper())
    return bool(full) and admin1 == full.lower()


def _geocode(query: str) -> dict:
    """Geocode ``query`` via Open-Meteo (EXACTLY ONE external call). Returns a
    resolved record dict; raises LocationNotFound / GeocoderUnavailable.

    Region/country preference is applied CLIENT-SIDE over the single result set
    (Open-Meteo returns results best-first). Selection order, never raising on a
    filter that excludes everything:
      1) the top-ranked result whose admin1 matches the region hint (further
         constrained to the country when a country token was supplied);
      2) else the top country-filtered result;
      3) else the overall top result.
    Every user-supplied component is URL-encoded via urlencode (quote)."""
    p = _parse_query(query)
    if not p.search_name:
        raise LocationNotFound("location service: empty query")

    params = {"name": p.search_name, "count": 10, "format": "json"}
    if p.url_country:
        # Open-Meteo accepts an ISO alpha-2 country filter.
        params["countryCode"] = p.url_country
    url = _GEOCODE_URL + "?" + urllib.parse.urlencode(params)

    data = _http_get_json(url)
    results = data.get("results") or []
    if not results:
        raise LocationNotFound("location service: no match for the requested place")

    has_country = bool(p.url_country or p.filter_code or p.filter_name)
    cc = p.url_country or p.filter_code

    # (1) Region match, top-ranked, constrained to the country when one was given.
    if p.region_hint:
        region_matches = [r for r in results if _matches_region(r, p.region_hint)]
        if has_country:
            constrained = [r for r in region_matches
                           if _matches_country(r, cc, p.filter_name)]
            region_matches = constrained or region_matches
        if region_matches:
            return _record_from_geocode(region_matches[0], query)

    # (2) Country-filtered top.
    if has_country:
        filtered = [r for r in results if _matches_country(r, cc, p.filter_name)]
        if filtered:
            return _record_from_geocode(filtered[0], query)

    # (3) Overall top.
    return _record_from_geocode(results[0], query)


def _record_from_geocode(r: dict, query: str) -> dict:
    """Build the stored/returned record shape from an Open-Meteo result."""
    return {
        "query": query,
        "display_name": r.get("name") or "",
        "region": r.get("admin1") or "",
        "country_code": str(r.get("country_code") or "").upper(),
        "country_name": r.get("country") or "",
        "lat": float(r["latitude"]),
        "lon": float(r["longitude"]),
    }


# ---------------------------------------------------------------------------
# Canonical label formatter
# ---------------------------------------------------------------------------

def display_label(record: dict) -> str:
    """The ONE canonical place label: 'City, Region, CountryName'.

    Drops a region that is empty OR redundant with the city or country (so no
    'City, , XX' and no 'Singapore, Singapore, Singapore'). Never a bare ISO
    code, never a US state abbreviation, never a '(zip)' suffix.
    """
    record = record or {}
    city = str(record.get("display_name") or "").strip()
    region = str(record.get("region") or "").strip()
    country = str(record.get("country_name") or "").strip()

    parts: list[str] = []
    if city:
        parts.append(city)

    # Drop a redundant region (matches city or country, case-insensitive).
    if region:
        low = region.lower()
        if low not in (city.lower(), country.lower()):
            parts.append(region)

    if country and country.lower() != city.lower():
        parts.append(country)

    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Cached-record validation (fail safe on a corrupted record)
# ---------------------------------------------------------------------------

_EXPECTED_KEYS = ("lat", "lon", "display_name", "country_code")


def _validate_record(record) -> dict | None:
    """Return a sanitized record if valid, else None (fail safe)."""
    if not isinstance(record, dict):
        return None
    if any(k not in record for k in _EXPECTED_KEYS):
        return None
    try:
        lat = float(record["lat"])
        lon = float(record["lon"])
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    out = dict(record)
    out["lat"] = lat
    out["lon"] = lon
    return out


# ---------------------------------------------------------------------------
# Settings access helpers
# ---------------------------------------------------------------------------

def _settings():
    from app_platform import settings as _s
    return _s


def _read_cached() -> dict | None:
    """Read the cached default_location setting; parse JSON if stored as a
    string. Returns None when unset/unreadable."""
    try:
        raw = _settings().get(_SETTING_KEY, scope="platform", default=None)
    except Exception:
        logger.debug("location service: reading default_location failed", exc_info=True)
        return None
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            logger.debug("location service: default_location is not valid JSON")
            return None
    if isinstance(raw, dict):
        return raw
    return None


def _write_cached(record: dict) -> None:
    _settings().set(_SETTING_KEY, json.dumps(record), scope="platform", by="location-service")


def _read_legacy_zip() -> str:
    try:
        raw = _settings().get(_LEGACY_ZIP_KEY, scope="platform", default="")
    except Exception:
        return ""
    return str(raw or "").strip().split("-")[0]


# ---------------------------------------------------------------------------
# Lazy migration: default_zip → default_location
# ---------------------------------------------------------------------------

def _migrate_legacy_zip() -> dict | None:
    """Migrate a legacy default_zip to default_location, geocoding it ONCE as a
    US postal. Idempotent (no-op once default_location exists). On geocode
    failure, leaves default_location unset and returns None — but the caller
    still has the legacy zip for a usable fallback. default_zip is retained.
    """
    zip_code = _read_legacy_zip()
    if not zip_code:
        return None
    # Validate as a US postal before it touches an outbound URL.
    if not zip_code.isdigit() or len(zip_code) != 5:
        logger.debug("location service: legacy default_zip is not a 5-digit US postal")
        return None
    try:
        # "<postal>,US" → country-filtered geocode (URL-encoded by _geocode).
        record = _geocode(f"{zip_code},US")
    except LocationError:
        logger.debug("location service: legacy zip migration geocode failed")
        return None
    try:
        _write_cached(record)
    except Exception:
        logger.debug("location service: writing migrated default_location failed",
                     exc_info=True)
        return None
    return record


def _legacy_fallback_record() -> dict | None:
    """A usable record derived from a legacy default_zip WITHOUT geocoding —
    used so resolve_location never returns the Settings error when a legacy zip
    exists but migration couldn't reach the geocoder."""
    zip_code = _read_legacy_zip()
    if not zip_code:
        return None
    return {
        "query": zip_code,
        "display_name": zip_code,
        "region": "",
        "country_code": "US",
        "country_name": "United States",
        "lat": None,
        "lon": None,
        "legacy_zip": zip_code,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_location(override: str | None = None) -> dict:
    """Resolve the location for a request.

    - override given → geocode it ON DEMAND (the only per-request external
      call) and NEVER silently fall back to the cached default. Its own
      offline/no-match/timeout path raises LocationError.
    - no override → the cached ``default_location`` (validated on read; NO
      geocoding). Lazily migrates a legacy ``default_zip`` on first read.
    - nothing configured and no override → a result carrying the location-free
      NO_LOCATION_MSG (never crashes).

    Returns a record dict: {lat, lon, display_label, region, country_code,
    country_name, display_name, ...}. When unconfigured, returns
    {configured: False, message: NO_LOCATION_MSG}.
    """
    if override is not None and str(override).strip():
        record = _geocode(str(override))  # raises on no-match / unreachable
        record["display_label"] = display_label(record)
        record["configured"] = True
        return record

    # No override → cached default (no geocoding).
    cached = _validate_record(_read_cached())
    if cached is None:
        # Try a lazy migration from a legacy zip, then a no-geocode fallback.
        migrated = _validate_record(_migrate_legacy_zip())
        if migrated is not None:
            cached = migrated
        else:
            legacy = _legacy_fallback_record()
            if legacy is not None:
                legacy = dict(legacy)
                legacy["display_label"] = display_label(legacy)
                legacy["configured"] = True
                return legacy
            return {"configured": False, "message": NO_LOCATION_MSG}

    out = dict(cached)
    out["display_label"] = display_label(out)
    out["configured"] = True
    return out


def save_default_location(query: str) -> dict:
    """Geocode ``query`` EXACTLY ONCE and store it as the platform
    ``default_location`` (RESOLVE-AND-STORE). Returns the resolved record (so
    Settings can show the matched label inline).

    On no match → raises LocationNotFound, previous value kept. On geocoder
    unreachable → raises GeocoderUnavailable, previous value kept. Never stores
    a partial/empty record.
    """
    q = (query or "").strip()
    if not q:
        raise LocationNotFound("location service: empty query")

    record = _geocode(q)  # raises LocationNotFound / GeocoderUnavailable

    # Guard: never store a partial/empty record.
    if record.get("lat") is None or record.get("lon") is None \
            or not record.get("display_name"):
        raise LocationNotFound("location service: incomplete geocode result")

    _write_cached(record)
    record["display_label"] = display_label(record)
    record["configured"] = True
    return record
