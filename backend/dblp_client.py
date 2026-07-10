"""DBLP enumeration client for the Conference Search feature.

Enumerates the *complete* accepted-paper list for a venue-year by reading DBLP
tables of contents (TOCs) — never a keyword search, which paginates/truncates.

Flow per venue:
  1. discover_tocs()  -> fetch the venue index HTML, extract per-year TOC keys.
  2. fetch_toc_hits() -> for each TOC key, page through the publ API `toc:` filter
                          (h=1000 + f offset) until every record is retrieved.
  3. parse_hit()      -> normalize DBLP's JSON quirks into flat records.

All raw responses are cached on disk under paths.CONFERENCE_RAW_DIR so a re-run
is reproducible from the snapshot and DBLP is not re-hit unnecessarily.

Note: live HTTP happens where the backend runs (the user's machine). Network
errors are surfaced with clear messages rather than silently yielding zero.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from . import paths


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context with a real CA bundle.

    The python.org interpreter (which the .venv is built on) ships without
    access to the macOS system trust store, so the default context raises
    CERTIFICATE_VERIFY_FAILED. Prefer certifi's bundle when available.
    """
    try:
        import certifi  # bundled via requests/httpx in this project
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - fall back to the default trust store
        return ssl.create_default_context()


_SSL_CTX = _ssl_context()

DBLP_BASE = "https://dblp.org"
PAGE_SIZE = 1000          # publ API max hits per request
POLITE_DELAY = 3.0        # seconds between live requests (DBLP asks for gentleness)
REQUEST_TIMEOUT = 90      # per-request socket timeout (DBLP can be slow)
MAX_RETRIES = 5           # retries on 429 / timeout / transient network errors
DEFAULT_BACKOFF = 10.0    # base backoff when DBLP sends no Retry-After
MAX_BACKOFF = 90.0        # cap a single wait so a fetch can't hang forever
TRY_BIBTEX = False        # per-proceedings .bib 404s on DBLP; use search API
CONTACT = os.environ.get("AGENTIC_SLR_CONTACT", "agentic-slr")
USER_AGENT = f"agentic-slr/0.1 (+{CONTACT})"

# TOC stems that are not the main track. Skipped when a venue's track == "main"
# and the corresponding include_* flag is off.
_WORKSHOP_HINTS = ("workshop", "-ws", "srw", "student", "tutorial", "demo", "-demos", "tiny")
_FINDINGS_HINTS = ("findings",)
_COMPANION_HINTS = ("companion", "-comp", "adjunct")

Logger = Callable[[str], None]


def _log(logger: Optional[Logger], msg: str) -> None:
    if logger:
        logger(msg)


# --------------------------------------------------------------------------- #
# Cached HTTP
# --------------------------------------------------------------------------- #
def _cache_path(url: str, ext: str):
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return paths.CONFERENCE_RAW_DIR / f"{h}{ext}"


def http_get(url: str, ext: str = ".txt", *, refresh: bool = False,
             logger: Optional[Logger] = None) -> str:
    """GET a URL with on-disk caching. Returns the response body as text."""
    paths.ensure_dirs()
    cp = _cache_path(url, ext)
    if cp.exists() and not refresh:
        return cp.read_text(encoding="utf-8")
    _log(logger, f"GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            cp.write_text(body, encoding="utf-8")
            time.sleep(POLITE_DELAY)
            return body
        except urllib.error.HTTPError as e:
            # Retry on rate-limits (429) and transient server errors (5xx).
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                try:
                    wait = float(retry_after) if retry_after else DEFAULT_BACKOFF * (2 ** attempt)
                except (TypeError, ValueError):
                    wait = DEFAULT_BACKOFF * (2 ** attempt)
                _log(logger, f"  HTTP {e.code}; waiting {min(wait, MAX_BACKOFF):.0f}s "
                             f"(retry {attempt + 1}/{MAX_RETRIES})")
                time.sleep(min(wait, MAX_BACKOFF))
                continue
            raise RuntimeError(f"DBLP request failed for {url}: {e}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Read/connect timeouts and transient network errors: back off + retry.
            if attempt < MAX_RETRIES:
                wait = min(DEFAULT_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                _log(logger, f"  network error ({e}); waiting {wait:.0f}s "
                             f"(retry {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            raise RuntimeError(f"DBLP request failed for {url}: {e}") from e
    raise RuntimeError(f"DBLP unreachable after {MAX_RETRIES} retries: {url}")


def _get_json(url: str, *, refresh: bool = False, logger: Optional[Logger] = None) -> dict:
    body = http_get(url, ext=".json", refresh=refresh, logger=logger)
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"DBLP returned non-JSON for {url}: {e}") from e


# --------------------------------------------------------------------------- #
# TOC discovery
# --------------------------------------------------------------------------- #
def _year_from_stem(stem: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", stem)
    return int(m.group(0)) if m else None


def _is_main_track(stem: str, *, include_workshops: bool,
                   include_companion: bool, track: str) -> bool:
    s = stem.lower()
    if track == "findings":
        return any(h in s for h in _FINDINGS_HINTS)
    # main track: exclude findings/workshop/companion volumes unless opted in
    if any(h in s for h in _FINDINGS_HINTS):
        return False
    if not include_workshops and any(h in s for h in _WORKSHOP_HINTS):
        return False
    if not include_companion and any(h in s for h in _COMPANION_HINTS):
        return False
    return True


def discover_tocs(dblp_key: str, year_start: int, year_end: int, *,
                  track: str = "main", include_workshops: bool = False,
                  include_companion: bool = False, refresh: bool = False,
                  logger: Optional[Logger] = None) -> list[dict[str, Any]]:
    """Return [{'year': int, 'toc_key': 'conf/nips/neurips2023'}] within range.

    Parses the venue index HTML for per-proceedings TOC links, which handles
    inconsistent stems (e.g. nips vs neurips) automatically.
    """
    index_url = f"{DBLP_BASE}/db/{dblp_key.strip('/')}/index.html"
    html = http_get(index_url, ext=".html", refresh=refresh, logger=logger)

    key_esc = re.escape(dblp_key.strip("/"))
    # Match links like .../db/conf/nips/neurips2023.html -> capture conf/nips/neurips2023
    pattern = re.compile(rf"db/({key_esc}/[A-Za-z0-9._-]+?)\.html")
    seen: dict[str, dict[str, Any]] = {}
    for stem_key in pattern.findall(html):
        stem = stem_key.rsplit("/", 1)[-1]
        year = _year_from_stem(stem)
        if year is None or not (year_start <= year <= year_end):
            continue
        if not _is_main_track(stem, include_workshops=include_workshops,
                              include_companion=include_companion, track=track):
            continue
        seen.setdefault(stem_key, {"year": year, "toc_key": stem_key})

    tocs = sorted(seen.values(), key=lambda t: (t["year"], t["toc_key"]))
    _log(logger, f"discovered {len(tocs)} TOC(s) for {dblp_key} in "
                 f"{year_start}-{year_end}: {[t['toc_key'] for t in tocs]}")
    return tocs


# --------------------------------------------------------------------------- #
# TOC enumeration
# --------------------------------------------------------------------------- #
def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def fetch_toc_hits(toc_key: str, *, refresh: bool = False,
                   logger: Optional[Logger] = None) -> list[dict[str, Any]]:
    """Page through the publ API `toc:` filter and return every hit's info dict.

    Advances the offset by the number of records DBLP actually returns (not a
    fixed page size): DBLP may cap a response below the requested `h` (e.g. when
    under load), so stepping by len(page) is the only way to page completely.
    """
    q = f"toc:db/{toc_key}.bht:"
    hits: list[dict[str, Any]] = []
    first = 0
    total = 0
    while True:
        params = urllib.parse.urlencode(
            {"q": q, "h": PAGE_SIZE, "f": first, "format": "json"}
        )
        url = f"{DBLP_BASE}/search/publ/api?{params}"
        data = _get_json(url, refresh=refresh, logger=logger)
        h = (((data or {}).get("result") or {}).get("hits") or {})
        total = int(h.get("@total", 0) or 0)
        page = [x.get("info", {}) for x in _as_list(h.get("hit")) if isinstance(x, dict)]
        if not page:
            break
        hits.extend(page)
        first += len(page)          # step by what DBLP actually sent
        if first >= total:
            break
        if first > 100000:          # safety valve against a pathological loop
            _log(logger, f"  {toc_key}: safety stop at {first} (total reported {total})")
            break
    note = "" if len(hits) >= total else f"  [WARNING: got {len(hits)} < reported {total}]"
    _log(logger, f"  {toc_key}: {len(hits)} of {total} hit(s) via search API{note}")
    return hits


# --------------------------------------------------------------------------- #
# BibTeX enumeration (single request per proceedings — gentlest on DBLP)
# --------------------------------------------------------------------------- #
def fetch_toc_bibtex(toc_key: str, *, refresh: bool = False,
                     logger: Optional[Logger] = None) -> str:
    """Fetch a whole proceedings as BibTeX in one request."""
    url = f"{DBLP_BASE}/db/{toc_key}.bib?param=1"
    return http_get(url, ext=".bib", refresh=refresh, logger=logger)


def _iter_bib_entries(text: str):
    """Yield (entry_type, citekey, fields_body) for each @entry in a BibTeX blob."""
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at == -1:
            return
        brace = text.find("{", at)
        if brace == -1:
            return
        etype = text[at + 1:brace].strip().lower()
        depth, j = 0, brace
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[brace + 1:j]
        comma = body.find(",")
        citekey = body[:comma].strip() if comma != -1 else ""
        fields_body = body[comma + 1:] if comma != -1 else ""
        yield etype, citekey, fields_body
        i = j + 1


def _bib_fields(s: str) -> dict[str, str]:
    """Extract field=value pairs from a BibTeX entry body (brace/quote aware)."""
    fields: dict[str, str] = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and not (s[i].isalpha()):
            i += 1
        start = i
        while i < n and (s[i].isalnum() or s[i] in "-_"):
            i += 1
        name = s[start:i].strip().lower()
        while i < n and s[i] in " \t\r\n":
            i += 1
        if i >= n or s[i] != "=":
            break
        i += 1
        while i < n and s[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if s[i] == "{":
            depth, j = 0, i
            while j < n:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            val, i = s[i + 1:j], j + 1
        elif s[i] == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 1
            val, i = s[i + 1:j], j + 1
        else:
            j = i
            while j < n and s[j] not in ",\n":
                j += 1
            val, i = s[i:j].strip(), j
        if name:
            fields[name] = val
    return fields


def _bib_clean(value: str) -> str:
    t = re.sub(r"[{}]", "", value or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:-1].strip() if t.endswith(".") else t


def _bib_authors(value: str) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    for part in re.split(r"\s+and\s+", value):
        name = _bib_clean(part)
        if "," in name:  # "Last, First" -> "First Last"
            last, _, first = name.partition(",")
            name = f"{first.strip()} {last.strip()}".strip()
        name = re.sub(r"\s+\d{4}$", "", name)  # strip DBLP disambiguation number
        if name:
            out.append(name)
    return out


_BIB_SKIP_TYPES = {"proceedings", "comment", "string", "preamble"}


def parse_bibtex(text: str, toc_key: str = "") -> list[dict[str, Any]]:
    """Parse a DBLP BibTeX blob into the same record shape as parse_hit()."""
    records: list[dict[str, Any]] = []
    for etype, citekey, body in _iter_bib_entries(text):
        if etype in _BIB_SKIP_TYPES:
            continue
        f = _bib_fields(body)
        title = _bib_clean(f.get("title", ""))
        if not title:
            continue
        ym = re.search(r"\d{4}", f.get("year", "") or "")
        key = citekey[5:] if citekey.startswith("DBLP:") else citekey
        records.append({
            "dblp_key": key,
            "title": title,
            "authors": _bib_authors(f.get("author", "")),
            "year": int(ym.group()) if ym else None,
            "doi": (f.get("doi", "") or "").strip(),
            "ee": (f.get("url", "") or "").strip(),
            "dblp_url": (f.get("biburl", "") or "").strip(),
            "venue_raw": _bib_clean(f.get("booktitle", "") or f.get("journal", "")),
            "type": etype,
            "toc_key": toc_key,
        })
    return records


def _looks_like_bibtex(text: str) -> bool:
    head = text.lstrip()[:4000].lower()
    if head.startswith("<"):        # HTML error/notice page, not BibTeX
        return False
    if "@" not in head:
        return False
    return True


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
_NON_PAPER_TYPES = {"editorship", "books and theses"}


def _clean_title(title: Any) -> str:
    if isinstance(title, dict):
        title = title.get("text", "")
    t = (title or "").strip()
    return t[:-1].strip() if t.endswith(".") else t


def _authors(info: dict) -> list[str]:
    node = (info.get("authors") or {}).get("author")
    out: list[str] = []
    for a in _as_list(node):
        if isinstance(a, dict):
            name = (a.get("text") or "").strip()
        else:
            name = str(a).strip()
        # DBLP disambiguates duplicate names with a trailing number, e.g. "Wei Wang 0001"
        name = re.sub(r"\s+\d{4}$", "", name)
        if name:
            out.append(name)
    return out


def parse_hit(info: dict, toc_key: str = "") -> Optional[dict[str, Any]]:
    """Normalize one DBLP publ-API `info` object into a flat record.

    Returns None for non-paper entries (proceedings editorship, front matter).
    """
    ptype = (info.get("type") or "").strip().lower()
    if ptype in _NON_PAPER_TYPES:
        return None
    title = _clean_title(info.get("title"))
    if not title:
        return None
    year = info.get("year")
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None
    ee = info.get("ee")
    ee = ee[0] if isinstance(ee, list) and ee else (ee if isinstance(ee, str) else "")
    return {
        "dblp_key": info.get("key", ""),
        "title": title,
        "authors": _authors(info),
        "year": year,
        "doi": (info.get("doi") or "").strip(),
        "ee": ee,
        "dblp_url": info.get("url", ""),
        "venue_raw": info.get("venue", ""),
        "type": info.get("type", ""),
        "toc_key": toc_key,
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def enumerate_venue(dblp_key: str, year_start: int, year_end: int, *,
                    track: str = "main", include_workshops: bool = False,
                    include_companion: bool = False, refresh: bool = False,
                    logger: Optional[Logger] = None,
                    on_toc: Optional[Callable[[dict, list], None]] = None) -> dict[str, Any]:
    """Enumerate all accepted papers for a venue across a year range.

    Each TOC (proceedings/year-volume) is fetched independently: a failure on one
    is logged and skipped (added to `failed_tocs`) rather than aborting the whole
    venue, so the years that succeeded are kept. Re-running retries the failed
    ones (cached pages make it resume cheaply). If `on_toc(toc, recs)` is given,
    it is called after each successful TOC so the caller can persist incrementally.

    Returns {'records', 'tocs', 'per_year', 'failed_tocs'}.
    """
    tocs = discover_tocs(
        dblp_key, year_start, year_end, track=track,
        include_workshops=include_workshops, include_companion=include_companion,
        refresh=refresh, logger=logger,
    )
    records: list[dict[str, Any]] = []
    per_year: dict[int, int] = {}
    failed: list[dict[str, Any]] = []
    for toc in tocs:
        try:
            recs = enumerate_toc(toc["toc_key"], refresh=refresh, logger=logger)
        except RuntimeError as e:
            _log(logger, f"  {toc['toc_key']}: FAILED ({e}); skipping — re-run to retry")
            failed.append({"toc_key": toc["toc_key"], "year": toc["year"], "error": str(e)})
            continue
        for rec in recs:
            if rec["year"] is None:
                rec["year"] = toc["year"]
        records.extend(recs)
        per_year[toc["year"]] = per_year.get(toc["year"], 0) + len(recs)
        if on_toc is not None:
            on_toc(toc, recs)
    return {"records": records, "tocs": tocs, "per_year": per_year, "failed_tocs": failed}


def enumerate_toc(toc_key: str, *, refresh: bool = False,
                  logger: Optional[Logger] = None) -> list[dict[str, Any]]:
    """Enumerate one proceedings: BibTeX first (1 request), search API on fallback.

    Falls back when the BibTeX endpoint errors, returns a non-BibTeX body (e.g.
    an HTML notice for an oversized export), or parses to zero records.

    NOTE: TRY_BIBTEX is disabled by default. DBLP does not serve a per-proceedings
    `.bib` file at db/<toc>.bib (it 404s); its BibTeX export routes through the
    same paginated search API, so there is no single-request win. The parser is
    retained for the day a real bulk endpoint is wired in.
    """
    if not TRY_BIBTEX:
        raw_hits = fetch_toc_hits(toc_key, refresh=refresh, logger=logger)
        return [r for r in (parse_hit(info, toc_key) for info in raw_hits) if r is not None]
    try:
        text = fetch_toc_bibtex(toc_key, refresh=refresh, logger=logger)
        if _looks_like_bibtex(text):
            recs = parse_bibtex(text, toc_key=toc_key)
            if recs:
                _log(logger, f"  {toc_key}: {len(recs)} record(s) via bibtex")
                return recs
        _log(logger, f"  {toc_key}: bibtex empty/unusable, falling back to search API")
    except RuntimeError as e:
        _log(logger, f"  {toc_key}: bibtex failed ({e}); falling back to search API")

    raw_hits = fetch_toc_hits(toc_key, refresh=refresh, logger=logger)
    return [r for r in (parse_hit(info, toc_key) for info in raw_hits) if r is not None]
