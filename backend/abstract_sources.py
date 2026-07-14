"""Abstract enrichment for the Conference Search feature (Phase 2).

Attaches abstracts to the DBLP-enumerated papers without changing membership:
DBLP decides what is in the review; these sources only supply abstract text.

Primary source is OpenAlex, used in *bulk* — for each venue-year we cursor-page
the works for that source+year (a few requests for thousands of papers) and then
match our DBLP papers to them by DOI, then exact normalized title, then fuzzy
title. Per-paper lookups (10k+ requests) are avoided.

Matching bands (plan §5):
  DOI equality                      -> accept  (confidence 1.0,  method 'doi')
  exact normalized-title equality   -> accept  (confidence 0.99, method 'title_exact')
  fuzzy title ratio >= 0.95         -> accept  (method 'title_fuzzy')
  0.85 <= ratio < 0.95              -> REVIEW  (not auto-attached; flagged)
  ratio < 0.85                      -> no match

Semantic Scholar and venue-native (OpenReview/PMLR/…) are planned as additional
sources for OpenAlex misses; the cascade skips sources not yet implemented.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from . import paths

OPENALEX_BASE = "https://api.openalex.org"
MAILTO = os.environ.get("OPENALEX_MAILTO") or os.environ.get("AGENTIC_SLR_CONTACT", "")
USER_AGENT = f"agentic-slr/0.2 (+{MAILTO or 'agentic-slr'})"
# OpenReview filters non-browser user agents (returns empty instead of data),
# so its requests use a browser-like UA.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Optional captcha bypass for OpenReview: solve the "I am not a robot" check once
# in a browser, then copy the cookie into .env. OpenReview uses its own token
# (openreview.clearanceToken, a JWT bound to your IP), not Cloudflare's.
#
# Preferred: OPENREVIEW_COOKIE = the FULL Cookie request header (from DevTools ->
#   Network -> the /notes request -> Request Headers -> Cookie), e.g.
#   "GCILB=...; openreview.clearanceToken=..."
# Or just: OPENREVIEW_CLEARANCE_TOKEN = the openreview.clearanceToken value.
# Also set OPENREVIEW_UA to your exact browser navigator.userAgent. Token expires,
# so run the enrich promptly after setting it.
OPENREVIEW_UA = os.environ.get("OPENREVIEW_UA", "").strip() or BROWSER_UA
_or_cookie = os.environ.get("OPENREVIEW_COOKIE", "").strip()
_or_token = os.environ.get("OPENREVIEW_CLEARANCE_TOKEN", "").strip()
if not _or_cookie and _or_token:
    _or_cookie = f"openreview.clearanceToken={_or_token}"
OPENREVIEW_COOKIE = _or_cookie or None


# Preferred OpenReview access: log in with a (free) account. Signing in skips
# the "Verifying your browser" challenge, so no captcha/token juggling. Set
# OPENREVIEW_USERNAME (email) and OPENREVIEW_PASSWORD in .env.
OPENREVIEW_USERNAME = os.environ.get("OPENREVIEW_USERNAME", "").strip()
OPENREVIEW_PASSWORD = os.environ.get("OPENREVIEW_PASSWORD", "").strip()
_OR_TOKEN: dict[str, Any] = {"token": None, "exp": 0.0}


def _post_json(url: str, payload: dict, *, logger: Optional[Logger] = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"User-Agent": OPENREVIEW_UA, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def openreview_token(*, logger: Optional[Logger] = None, force: bool = False) -> Optional[str]:
    """Log in to OpenReview and cache a bearer token (skips the browser check)."""
    if not (OPENREVIEW_USERNAME and OPENREVIEW_PASSWORD):
        return None
    now = time.time()
    if not force and _OR_TOKEN["token"] and now < _OR_TOKEN["exp"]:
        return _OR_TOKEN["token"]
    for base in (OPENREVIEW_API2, OPENREVIEW_API1):
        try:
            data = _post_json(f"{base}/login",
                              {"id": OPENREVIEW_USERNAME, "password": OPENREVIEW_PASSWORD},
                              logger=logger)
        except Exception as e:  # noqa: BLE001
            _log(logger, f"  OpenReview login failed via {base}: {e}")
            continue
        tok = data.get("token") or data.get("access_token")
        if tok:
            _OR_TOKEN["token"] = tok
            _OR_TOKEN["exp"] = now + 3000  # refresh well before typical expiry
            _log(logger, f"  OpenReview: signed in as {OPENREVIEW_USERNAME} (browser check bypassed)")
            return tok
    _log(logger, "  OpenReview: login returned no token (check credentials)")
    return None


def _normalize_or_cookie(raw: Optional[str]) -> Optional[str]:
    """Accept either a full Cookie header or a bare token.

    If the value has no '=' (someone pasted just the clearanceToken JWT), wrap it
    as the cookie OpenReview expects.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    return raw if "=" in raw else f"openreview.clearanceToken={raw}"
POLITE_DELAY = 0.2          # OpenAlex polite pool allows ~10 req/s
REQUEST_TIMEOUT = 45        # fail a hung request sooner so we can retry/move on
MAX_RETRIES = 3
DEFAULT_BACKOFF = 5.0
MAX_BACKOFF = 45.0

# Matching thresholds
ACCEPT_FUZZY = 0.95
REVIEW_FUZZY = 0.85

Logger = Callable[[str], None]


def _log(logger: Optional[Logger], msg: str) -> None:
    if logger:
        logger(msg)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


_SSL_CTX = _ssl_context()


# --------------------------------------------------------------------------- #
# Cached HTTP (JSON)
# --------------------------------------------------------------------------- #
def _cache_path(url: str):
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return paths.CONFERENCE_RAW_DIR / f"oa_{h}.json"


def get_json(url: str, *, refresh: bool = False, logger: Optional[Logger] = None,
             accept: Optional[Callable[[dict], bool]] = None,
             user_agent: Optional[str] = None, cookie: Optional[str] = None,
             bearer: Optional[str] = None) -> dict:
    """GET a JSON URL with on-disk caching + retry/backoff on 429/5xx/timeouts.

    ``accept`` guards caching: a response is only read-from / written-to cache
    when accept(data) is true. This stops a throttled-empty response (HTTP 200
    with no results) from being cached and stuck — it will be re-fetched next run.
    ``user_agent`` overrides the default (OpenReview needs a browser-like UA).
    """
    paths.ensure_dirs()
    cp = _cache_path(url)
    if cp.exists() and not refresh:
        try:
            cached = json.loads(cp.read_text(encoding="utf-8"))
            if accept is None or accept(cached):
                return cached
        except json.JSONDecodeError:
            pass  # fall through and re-fetch
    _log(logger, f"GET {url}")
    headers = {"User-Agent": user_agent or USER_AGENT}
    if cookie:
        headers["Cookie"] = cookie
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            if accept is None or accept(data):
                cp.write_text(body, encoding="utf-8")  # only cache useful responses
            time.sleep(POLITE_DELAY)
            return data
        except urllib.error.HTTPError as e:
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
            raise RuntimeError(f"OpenAlex request failed for {url}: {e}") from e
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            if attempt < MAX_RETRIES:
                wait = min(DEFAULT_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                _log(logger, f"  error ({e}); waiting {wait:.0f}s "
                             f"(retry {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            raise RuntimeError(f"OpenAlex request failed for {url}: {e}") from e
    raise RuntimeError(f"OpenAlex unreachable after {MAX_RETRIES} retries: {url}")


def _mailto_param() -> str:
    return f"&mailto={urllib.parse.quote(MAILTO)}" if MAILTO else ""


# --------------------------------------------------------------------------- #
# Text normalization + fuzzy matching
# --------------------------------------------------------------------------- #
def normalize_title(title: str) -> str:
    """Lowercase, strip markup/LaTeX, fold unicode, drop punctuation, collapse ws."""
    t = (title or "").lower()
    t = re.sub(r"\$[^$]*\$", " ", t)          # strip inline LaTeX math
    t = re.sub(r"[{}\\]", " ", t)              # strip LaTeX braces/backslashes
    t = re.sub(r"<[^>]+>", " ", t)             # strip HTML tags
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t)          # drop punctuation
    return re.sub(r"\s+", " ", t).strip()


def _difflib_ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


try:  # rapidfuzz is faster + token-aware; fall back to stdlib difflib
    from rapidfuzz.fuzz import token_sort_ratio as _rf_token_sort

    def title_ratio(a: str, b: str) -> float:
        return _rf_token_sort(a, b) / 100.0
    _FUZZ_BACKEND = "rapidfuzz"
except Exception:  # noqa: BLE001
    def title_ratio(a: str, b: str) -> float:
        return _difflib_ratio(a, b)
    _FUZZ_BACKEND = "difflib"


def normalize_doi(doi: str) -> str:
    d = (doi or "").strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d


# --------------------------------------------------------------------------- #
# OpenAlex abstract reconstruction
# --------------------------------------------------------------------------- #
def reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    """OpenAlex stores abstracts as a word -> [positions] inverted index."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(w for _, w in positions).strip()


# --------------------------------------------------------------------------- #
# OpenAlex source resolution + bulk works
# --------------------------------------------------------------------------- #
def _short_id(openalex_id: str) -> str:
    """'https://openalex.org/S12345' -> 'S12345'."""
    return (openalex_id or "").rstrip("/").rsplit("/", 1)[-1]


# Full venue names for OpenAlex source resolution — acronyms collide badly
# (e.g. "ICLR" matches a law review), so search by the full name.
OPENALEX_QUERY = {
    "iclr": "International Conference on Learning Representations",
    "neurips": "Neural Information Processing Systems",
    "icml": "International Conference on Machine Learning",
    "acl": "Annual Meeting of the Association for Computational Linguistics",
    "emnlp": "Conference on Empirical Methods in Natural Language Processing",
    "naacl": "North American Chapter of the Association for Computational Linguistics",
    "cvpr": "IEEE Conference on Computer Vision and Pattern Recognition",
    "iccv": "IEEE International Conference on Computer Vision",
    "eccv": "European Conference on Computer Vision",
    "aaai": "AAAI Conference on Artificial Intelligence",
    "ijcai": "International Joint Conference on Artificial Intelligence",
    "kdd": "Knowledge Discovery and Data Mining",
    "www": "The Web Conference",
    "sigir": "International ACM SIGIR Conference on Research and Development in Information Retrieval",
}


def openalex_source_id(name: str, *, refresh: bool = False,
                       logger: Optional[Logger] = None) -> Optional[str]:
    """Resolve a venue name to its OpenAlex source id (e.g. 'S4306419637').

    Picks the candidate with the most works (a real venue has thousands; a
    coincidental acronym match is small) and rejects a zero-works result, so a
    wrong-acronym source can never be silently used.
    """
    q = urllib.parse.quote(name)
    url = f"{OPENALEX_BASE}/sources?search={q}&per-page=25{_mailto_param()}"
    data = get_json(url, refresh=refresh, logger=logger)
    results = data.get("results") or []
    if not results:
        _log(logger, f"  OpenAlex: no source found for '{name}'")
        return None
    best = max(results, key=lambda r: r.get("works_count", 0) or 0)
    if (best.get("works_count", 0) or 0) == 0:
        _log(logger, f"  OpenAlex: best match for '{name}' has 0 works — treating as unresolved")
        return None
    sid = _short_id(best.get("id", ""))
    _log(logger, f"  OpenAlex source for '{name}': {sid} "
                 f"({best.get('display_name')}, {best.get('works_count')} works)")
    return sid or None


# --------------------------------------------------------------------------- #
# OpenReview (venue-native; best for ICLR/NeurIPS — no DOIs, keyed by forum id)
# --------------------------------------------------------------------------- #
OPENREVIEW_API2 = "https://api2.openreview.net"
OPENREVIEW_API1 = "https://api.openreview.net"
# Which venues live on OpenReview, and their group prefix.
OPENREVIEW_GROUP = {"iclr": "ICLR.cc", "neurips": "NeurIPS.cc"}


def openreview_id_from_url(url: str) -> Optional[str]:
    """Extract the forum/note id from an OpenReview URL (…?id=XXXX or &id=XXXX)."""
    m = re.search(r"[?&]id=([^&#]+)", url or "")
    return m.group(1) if m else None


def _openreview_abstract_from_note(note: dict) -> str:
    content = note.get("content") or {}
    ab = content.get("abstract")
    if isinstance(ab, dict):     # API v2 wraps values: {"value": ...}
        ab = ab.get("value")
    return (ab or "").strip()


def openreview_abstract(note_id: str, *, refresh: bool = False,
                        logger: Optional[Logger] = None,
                        cookie: Optional[str] = None,
                        user_agent: Optional[str] = None) -> str:
    """Fetch one paper's abstract by note id (per-id fallback). Tries v2 then v1."""
    ck = _normalize_or_cookie(cookie) or OPENREVIEW_COOKIE
    ua = user_agent if user_agent else OPENREVIEW_UA
    bearer = openreview_token(logger=logger)
    for base in (OPENREVIEW_API2, OPENREVIEW_API1):
        try:
            data = get_json(f"{base}/notes?id={urllib.parse.quote(note_id)}",
                            refresh=refresh, logger=logger,
                            accept=lambda d: bool(d.get("notes")),
                            user_agent=ua, cookie=ck, bearer=bearer)
        except RuntimeError:
            continue
        for note in (data.get("notes") or []):
            ab = _openreview_abstract_from_note(note)
            if ab:
                return ab
    return ""


def _openreview_query_forms(group: str, year: int) -> list[tuple[str, str]]:
    """(base_url, query) forms to try, covering v2 and v1 eras.

    v2 (api2) uses content.venueid; v1 (api) uses the Blind_Submission invitation.
    Newer venues are on v2, ICLR/NeurIPS <=~2023 on v1 — try both and use whatever
    returns notes.
    """
    vid = f"{group}/{year}/Conference"
    # Two forms only, to keep request volume (and throttling) low:
    #   v2 content.venueid  — the modern venues (≈2023+)
    #   v1 Blind_Submission — the older venues
    return [
        (OPENREVIEW_API2, f"content.venueid={urllib.parse.quote(vid)}"),
        (OPENREVIEW_API1, f"invitation={urllib.parse.quote(vid + '/-/Blind_Submission')}"),
    ]


def openreview_bulk(group: str, year: int, *, refresh: bool = False,
                    logger: Optional[Logger] = None,
                    cookie: Optional[str] = None,
                    user_agent: Optional[str] = None) -> dict[str, str]:
    """Bulk-fetch id->abstract for a venue-year in a few requests.

    Tries several query forms (v2 venueid, v1 invitation, …) and uses the first
    that returns notes, so it works across OpenReview's API eras. Misses are
    covered by the caller's (capped) per-id fallback, so an imperfect query only
    costs a few extra lookups, never wrong or missing data. ``cookie``/``user_agent``
    override the env defaults (e.g. a captcha token pasted at enrich time).
    """
    ck = _normalize_or_cookie(cookie) or OPENREVIEW_COOKIE
    ua = user_agent if user_agent else OPENREVIEW_UA
    bearer = openreview_token(logger=logger)
    for base, query in _openreview_query_forms(group, year):
        out: dict[str, str] = {}
        offset, total, seen = 0, 0, 0
        try:
            while True:
                url = f"{base}/notes?{query}&limit=1000&offset={offset}"
                data = get_json(url, refresh=refresh, logger=logger,
                                accept=lambda d: bool(d.get("notes")),
                                user_agent=ua, cookie=ck, bearer=bearer)
                notes = data.get("notes") or []
                total = int(data.get("count", 0) or 0)
                if not notes:
                    break
                for n in notes:
                    ab = _openreview_abstract_from_note(n)
                    if ab and n.get("id") and n["id"] not in out:
                        out[n["id"]] = ab
                seen += len(notes)
                offset += len(notes)
                if total and seen >= total:
                    break
                if not total and len(notes) < 1000:  # no count -> page-size heuristic
                    break
        except RuntimeError:
            continue
        if seen:
            note = "" if seen >= total else f"  [WARNING: paged {seen} of {total} notes]"
            _log(logger, f"  OpenReview bulk {group}/{year} via {base.split('//')[1]} "
                         f"[{query.split('=')[0]}]: {len(out)} abstracts from {seen} notes{note}")
            return out
    _log(logger, f"  OpenReview bulk {group}/{year}: 0 (no query form matched / API unavailable)")
    return {}


def openalex_by_dois(dois: list[str], *, refresh: bool = False,
                     logger: Optional[Logger] = None) -> dict[str, str]:
    """Look up abstracts directly by DOI (batches of 50) — source-independent.

    Returns {normalized_doi: abstract}. This is exact and doesn't depend on the
    venue's OpenAlex source being complete, so it's the right path for the many
    venues whose DBLP records carry DOIs (ACL, CVPR, AAAI, KDD, …).
    """
    norm = sorted({normalize_doi(d) for d in dois if d})
    out: dict[str, str] = {}
    for i in range(0, len(norm), 50):
        chunk = norm[i:i + 50]
        filt = "doi:" + "|".join(urllib.parse.quote(d, safe="") for d in chunk)
        url = (f"{OPENALEX_BASE}/works?filter={filt}"
               f"&per-page=50&select=doi,abstract_inverted_index{_mailto_param()}")
        try:
            data = get_json(url, refresh=refresh, logger=logger)
        except RuntimeError as e:
            _log(logger, f"  OpenAlex DOI batch failed ({e}); skipping chunk")
            continue
        for w in data.get("results") or []:
            d = normalize_doi(w.get("doi") or "")
            ab = reconstruct_abstract(w.get("abstract_inverted_index"))
            if d and ab and not _looks_like_citation(ab):  # reject OpenAlex citation-junk
                out[d] = ab
    _log(logger, f"  OpenAlex DOI lookup: {len(out)} abstracts for {len(norm)} DOIs")
    return out


def openalex_works(source_id: str, year: int, *, refresh: bool = False,
                   logger: Optional[Logger] = None) -> list[dict[str, Any]]:
    """Cursor-page all works for a source+year. Returns {title, doi, abstract}."""
    works: list[dict[str, Any]] = []
    cursor = "*"
    select = "title,doi,abstract_inverted_index"
    fltr = f"primary_location.source.id:{source_id},publication_year:{year}"
    while cursor:
        url = (f"{OPENALEX_BASE}/works?filter={fltr}"
               f"&per-page=200&select={select}&cursor={urllib.parse.quote(cursor)}"
               f"{_mailto_param()}")
        data = get_json(url, refresh=refresh, logger=logger)
        for w in data.get("results") or []:
            works.append({
                "title": w.get("title") or "",
                "doi": normalize_doi(w.get("doi") or ""),
                "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
            })
        cursor = ((data.get("meta") or {}).get("next_cursor"))
        if not (data.get("results")):
            break
    _log(logger, f"  OpenAlex works for source {source_id} {year}: {len(works)}")
    return works


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Semantic Scholar — batch abstract lookup by exact id (DOI / DBLP / ACL / arXiv)
# --------------------------------------------------------------------------- #
S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_API_KEY = os.environ.get("S2_API_KEY", "").strip()
S2_DELAY = 1.1            # introductory limit is 1 request/second
S2_BATCH = 500           # /paper/batch accepts up to 500 ids per request


def _s2_post(path: str, payload: dict, *, refresh: bool = False,
             logger: Optional[Logger] = None) -> Any:
    """POST to Semantic Scholar with the API key, cached by payload."""
    paths.ensure_dirs()
    key = hashlib.sha1((path + json.dumps(payload, sort_keys=True)).encode()).hexdigest()[:16]
    cp = paths.CONFERENCE_RAW_DIR / f"s2_{key}.json"
    if cp.exists() and not refresh:
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    url = f"{S2_BASE}{path}"
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY
    body = json.dumps(payload).encode("utf-8")
    _log(logger, f"POST {url} ({len(payload.get('ids', []))} ids)")
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            cp.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(S2_DELAY)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                try:
                    wait = float(retry_after) if retry_after else DEFAULT_BACKOFF * (2 ** attempt)
                except (TypeError, ValueError):
                    wait = DEFAULT_BACKOFF * (2 ** attempt)
                _log(logger, f"  S2 HTTP {e.code}; waiting {min(wait, MAX_BACKOFF):.0f}s")
                time.sleep(min(wait, MAX_BACKOFF))
                continue
            raise RuntimeError(f"S2 request failed for {url}: {e}") from e
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            if attempt < MAX_RETRIES:
                time.sleep(min(DEFAULT_BACKOFF * (2 ** attempt), MAX_BACKOFF))
                continue
            raise RuntimeError(f"S2 request failed for {url}: {e}") from e
    raise RuntimeError(f"S2 unreachable after {MAX_RETRIES} retries: {url}")


def s2_batch_abstracts(ids: list[str], *, refresh: bool = False,
                       logger: Optional[Logger] = None) -> dict[str, str]:
    """Look up abstracts for S2-formatted ids (e.g. 'DOI:...', 'DBLP:conf/...').

    Returns {id: abstract}. Results come back in input order (null when not
    found), so we zip them back to the ids. Citation-junk is rejected.
    """
    uniq = list(dict.fromkeys(i for i in ids if i))
    out: dict[str, str] = {}
    for i in range(0, len(uniq), S2_BATCH):
        chunk = uniq[i:i + S2_BATCH]
        try:
            data = _s2_post("/paper/batch?fields=abstract", {"ids": chunk},
                            refresh=refresh, logger=logger)
        except RuntimeError as e:
            _log(logger, f"  S2 batch failed ({e}); skipping chunk")
            continue
        for id_, rec in zip(chunk, data or []):
            if rec and rec.get("abstract") and not _looks_like_citation(rec["abstract"]):
                out[id_] = rec["abstract"]
    _log(logger, f"  S2: {len(out)} abstracts for {len(uniq)} ids")
    return out


# --------------------------------------------------------------------------- #
# Paper homepage extraction (venue-native fallback for open, non-captcha pages)
# --------------------------------------------------------------------------- #
# Domains that block automated access (captcha / bot-wall) — never scraped here.
HOMEPAGE_SKIP_DOMAINS = ("openreview.net", "dl.acm.org", "ieeexplore.ieee.org")


def get_text(url: str, *, refresh: bool = False, logger: Optional[Logger] = None) -> str:
    """Fetch a page as text (cached, browser UA). Returns '' on any failure —
    a paper whose page can't be reached just stays without an abstract."""
    paths.ensure_dirs()
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    cp = paths.CONFERENCE_RAW_DIR / f"hp_{h}.txt"
    if cp.exists() and not refresh:
        return cp.read_text(encoding="utf-8")
    _log(logger, f"GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            cp.write_text(body, encoding="utf-8")
            time.sleep(POLITE_DELAY)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(min(DEFAULT_BACKOFF * (2 ** attempt), MAX_BACKOFF))
                continue
            return ""
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < MAX_RETRIES:
                time.sleep(min(DEFAULT_BACKOFF * (2 ** attempt), MAX_BACKOFF))
                continue
            return ""
    return ""


def _strip_html(s: str) -> str:
    import html as _html
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = _html.unescape(s)
    s = re.sub(r"\\url\{([^}]*)\}", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _bibtex_abstract(text: str) -> str:
    """Pull the abstract field out of a BibTeX blob (e.g. ACL Anthology .bib)."""
    from . import dblp_client
    for _etype, _key, body in dblp_client._iter_bib_entries(text):
        ab = dblp_client._bib_fields(body).get("abstract")
        if ab:
            return _strip_html(ab)
    return ""


_ABSTRACT_HTML_PATTERNS = [
    # Highwire citation_abstract meta (PMLR, AAAI/OJS, many publishers), both attr orders
    r'<meta[^>]+name=["\']citation_abstract["\'][^>]+content=["\'](.*?)["\']',
    r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']citation_abstract["\']',
    r'<div[^>]+class=["\'][^"\']*acl-abstract[^"\']*["\'][^>]*>.*?<span[^>]*>(.*?)</span>',  # ACL (class)
    r'>\s*Abstract\s*</h5>\s*<span[^>]*>(.*?)</span>',                                        # ACL (h5 + span)
    r'>\s*Abstract\s*</h5>\s*<div[^>]*>(.*?)</div>',                                          # ACL (h5 + div)
    r'<div[^>]+id=["\']abstract["\'][^>]*>(.*?)</div>',                                       # CVF
    r'Abstract\s*</h4>\s*<p[^>]*>(.*?)</p>',                                                  # papers.nips.cc (legacy)
    r'class=["\'][^"\']*paper-abstract[^"\']*["\'][^>]*>(.*?)</p>',                            # papers.nips.cc (current)
    r'<div[^>]+class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</div>',                      # generic
]


def _looks_like_citation(text: str) -> str:
    """True if the text looks like a citation/author-publisher line, not an abstract."""
    t = (text or "").strip()
    if len(t) < 60:                                    # too short to be an abstract
        return True
    if "Proceedings of the" in t[:300] and len(t) < 600:  # e.g. "Authors. Proceedings of the …"
        return True
    return False


def _extract_abstract_html(html: str) -> str:
    for pat in _ABSTRACT_HTML_PATTERNS:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            cleaned = _strip_html(m.group(1))
            if len(cleaned) >= 40 and not _looks_like_citation(cleaned):
                return cleaned
    return ""


def _acl_anthology_id(url: str, doi: str) -> Optional[str]:
    """Anthology id (e.g. 2022.acl-long.1) from an aclanthology URL or an ACL DOI."""
    if "aclanthology.org" in (url or ""):
        return url.split("aclanthology.org/")[-1].split("?")[0].strip("/") or None
    m = re.search(r"10\.18653/v\d+/(.+)$", (doi or "").lower())
    return m.group(1) if m else None


def homepage_abstract(url: str, *, doi: str = "", refresh: bool = False,
                      logger: Optional[Logger] = None) -> str:
    """Fetch a paper's abstract from its own page. Skips captcha/bot-walled domains
    (OpenReview, ACM, IEEE). Uses a structured endpoint where a site offers one,
    and rejects citation/author-publisher text."""
    if not url:
        return ""
    domain = urllib.parse.urlparse(url).netloc.lower()
    if any(skip in domain for skip in HOMEPAGE_SKIP_DOMAINS):
        return ""
    # ACL Anthology (by domain or by ACL DOI, incl. doi.org redirects): scrape the
    # paper page. (The per-paper .bib does NOT include the abstract, only the HTML does.)
    acl_id = _acl_anthology_id(url, doi)
    if acl_id:
        html = get_text(f"https://aclanthology.org/{acl_id}/", refresh=refresh, logger=logger)
        return _extract_abstract_html(html)
    return _extract_abstract_html(get_text(url, refresh=refresh, logger=logger))


def build_index(works: list[dict[str, Any]]):
    """Build (by_doi, by_title, normed_list) lookups over OpenAlex works."""
    by_doi: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    normed: list[tuple[str, dict]] = []
    for w in works:
        if not w.get("abstract") or _looks_like_citation(w["abstract"]):
            continue  # no abstract, or OpenAlex citation-junk — useless for enrichment
        if w.get("doi"):
            by_doi.setdefault(w["doi"], w)
        nt = normalize_title(w.get("title", ""))
        if nt:
            by_title.setdefault(nt, w)
            normed.append((nt, w))
    return by_doi, by_title, normed


def match_paper(paper: dict, by_doi: dict, by_title: dict,
                normed: list[tuple[str, dict]]) -> Optional[dict[str, Any]]:
    """Return a match dict {abstract, method, confidence, needs_review} or None."""
    doi = normalize_doi(paper.get("doi", ""))
    if doi and doi in by_doi:
        return {"abstract": by_doi[doi]["abstract"], "method": "doi",
                "confidence": 1.0, "needs_review": False}
    nt = normalize_title(paper.get("title", ""))
    if not nt:
        return None
    if nt in by_title:
        return {"abstract": by_title[nt]["abstract"], "method": "title_exact",
                "confidence": 0.99, "needs_review": False}
    # fuzzy: best candidate
    best_ratio, best = 0.0, None
    for cand_nt, w in normed:
        r = title_ratio(nt, cand_nt)
        if r > best_ratio:
            best_ratio, best = r, w
    if best is None or best_ratio < REVIEW_FUZZY:
        return None
    return {
        "abstract": best["abstract"] if best_ratio >= ACCEPT_FUZZY else "",
        "candidate_title": best["title"],
        "method": "title_fuzzy" if best_ratio >= ACCEPT_FUZZY else "title_fuzzy_review",
        "confidence": round(best_ratio, 4),
        "needs_review": best_ratio < ACCEPT_FUZZY,
    }
