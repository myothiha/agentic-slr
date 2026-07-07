"""Parse bibliographic exports (RIS / CSV / BibTeX / Excel) into a uniform record format.

Each parser returns a list of "canonical" dicts with these keys:
    title, authors (list[str]), year (int|None), abstract,
    keywords (list[str]), doi, venue, url, raw (dict)

The ingestion layer adds `index`, `database`, `database_id` and `source_file`.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Optional

CANONICAL_KEYS = ["title", "authors", "year", "abstract", "keywords", "doi", "venue", "url"]


# --------------------------------------------------------------------------- #
# Page-count extraction (used by the Page Filter stage)
# --------------------------------------------------------------------------- #
_COUNT_KEYS = {
    "numpages", "number of pages", "page count", "pagecount", "no. of pages",
    "no of pages", "pages_count", "num pages",
}
_START_KEYS = {
    "start page", "page start", "beginning page", "starting page", "first page",
    "sp", "bp", "spage",
}
_END_KEYS = {"end page", "page end", "ending page", "last page", "ep", "epage"}
_RANGE_KEYS = {"pages", "page range", "pp", "page"}


def _first_int(value: Any) -> Optional[int]:
    m = re.search(r"\d+", str(value or ""))
    return int(m.group(0)) if m else None


def extract_pages(raw: dict[str, Any] | None) -> dict[str, Optional[int]]:
    """Derive (start, end, count) page numbers from a raw record dict.

    Handles explicit counts (numpages / Number of Pages), start+end pairs
    (Start Page / End Page, Page start / Page end, SP / EP), and range strings
    such as "2584-2593" or "2584–2593" in a 'pages' field. Returns None values
    when the data is unavailable.
    """
    if not raw:
        return {"start": None, "end": None, "count": None}
    lower = {str(k).lower().strip(): v for k, v in raw.items()}

    count = None
    for k in _COUNT_KEYS:
        if k in lower:
            count = _first_int(lower[k])
            if count:
                break

    start = next((_first_int(lower[k]) for k in _START_KEYS if k in lower and _first_int(lower[k])), None)
    end = next((_first_int(lower[k]) for k in _END_KEYS if k in lower and _first_int(lower[k])), None)

    if count is None and start is not None and end is not None and end >= start:
        count = end - start + 1

    if count is None:
        # Try a range string like "123-130" / "123–130" / "123--130".
        for k in _RANGE_KEYS:
            if k in lower:
                nums = re.findall(r"\d+", str(lower[k]))
                if len(nums) >= 2:
                    a, b = int(nums[0]), int(nums[-1])
                    if b >= a:
                        start = start or a
                        end = end or b
                        count = b - a + 1
                        break

    # A zero/negative count is meaningless; treat as unknown.
    if count is not None and count <= 0:
        count = None
    return {"start": start, "end": end, "count": count}


def _blank_record() -> dict[str, Any]:
    return {
        "title": "",
        "authors": [],
        "year": None,
        "abstract": "",
        "keywords": [],
        "doi": "",
        "venue": "",
        "url": "",
        "early_access": False,
        "raw": {},
    }


def derive_early_access(raw: dict[str, Any] | None) -> bool:
    """Detect an 'early access' / 'ahead of print' record from its raw columns.

    Databases name this differently:
      * Web of Science -> Document Type contains "Early Access"
      * Scopus         -> Publication Stage is "Article in press"
    IEEE exports have no such field, so this returns False for them.
    """
    if not raw:
        return False
    low = {str(k).lower().strip(): str(v) for k, v in raw.items()}
    if "early access" in low.get("document type", "").lower():
        return True
    if "in press" in low.get("publication stage", "").lower():
        return True
    return False


def _coerce_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(value))
    return int(m.group(0)) if m else None


def _split_multi(value: str) -> list[str]:
    """Split a delimited string of authors/keywords into a clean list."""
    if not value:
        return []
    parts = re.split(r"[;\n]", value)
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------- #
# RIS
# --------------------------------------------------------------------------- #
RIS_MAP = {
    "TI": "title", "T1": "title",
    "AB": "abstract", "N2": "abstract",
    "PY": "year", "Y1": "year", "DA": "year",
    "DO": "doi",
    "UR": "url", "L1": "url",
    "JO": "venue", "JF": "venue", "JA": "venue", "T2": "venue", "BT": "venue",
}
RIS_AUTHOR_TAGS = {"AU", "A1", "A2", "A3", "A4"}
RIS_KEYWORD_TAGS = {"KW"}


def parse_ris(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    last_tag: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n").rstrip("\r")
        m = re.match(r"^([A-Z][A-Z0-9])\s{0,2}-\s?(.*)$", line)
        if m:
            tag, value = m.group(1), m.group(2).strip()
            last_tag = tag
            if tag == "TY":
                current = _blank_record()
                records.append(current)
                current["raw"]["TY"] = value
                continue
            if current is None:
                current = _blank_record()
                records.append(current)
            if tag == "ER":
                current = None
                last_tag = None
                continue
            if tag in RIS_AUTHOR_TAGS:
                if value:
                    current["authors"].append(value)
            elif tag in RIS_KEYWORD_TAGS:
                if value:
                    current["keywords"].append(value)
            elif tag in RIS_MAP:
                field = RIS_MAP[tag]
                if field == "year":
                    current["year"] = current["year"] or _coerce_year(value)
                elif not current[field]:
                    current[field] = value
            current["raw"].setdefault(tag, value)
        elif current is not None and last_tag and line.strip():
            # continuation line of the previous tag
            if last_tag in ("AB", "N2"):
                current["abstract"] = (current["abstract"] + " " + line.strip()).strip()

    return [r for r in records if any([r["title"], r["abstract"], r["authors"]])]


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
CSV_FIELD_ALIASES = {
    "title": ["title", "document title", "article title", "primary title"],
    "abstract": ["abstract", "abstract note", "summary"],
    "year": ["year", "publication year", "pub year", "date", "publication date"],
    "doi": ["doi", "digital object identifier"],
    "url": ["url", "link", "pdf link", "document link"],
    "venue": [
        "venue", "source title", "source", "journal", "publication title",
        "conference name", "book title", "publication name",
    ],
    "authors": ["authors", "author", "author names", "author full names", "creator"],
    "keywords": [
        "keywords", "author keywords", "index keywords", "indexed keywords",
        "ieee terms", "tags", "keyword",
    ],
}


def _build_header_index(headers: list[str]) -> dict[str, str]:
    """Map canonical field -> actual header name found in the CSV."""
    lower = {h.lower().strip(): h for h in headers}
    resolved: dict[str, str] = {}
    for field, aliases in CSV_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in lower:
                resolved[field] = lower[alias]
                break
    return resolved


def _rows_to_records(
    fieldnames: list[str], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Turn header-keyed row dicts (from CSV or Excel) into canonical records."""
    header_index = _build_header_index(fieldnames)
    records: list[dict[str, Any]] = []
    for row in rows:
        rec = _blank_record()
        rec["raw"] = {k: v for k, v in row.items() if k and v}
        rec["early_access"] = derive_early_access(rec["raw"])
        for field, header in header_index.items():
            value = (row.get(header) or "").strip()
            if not value:
                continue
            if field == "authors":
                rec["authors"] = _split_multi(value)
            elif field == "keywords":
                rec["keywords"] = _split_multi(value)
            elif field == "year":
                rec["year"] = _coerce_year(value)
            else:
                rec[field] = value
        if any([rec["title"], rec["abstract"], rec["authors"]]):
            records.append(rec)
    return records


def parse_csv(text: str) -> list[dict[str, Any]]:
    # Strip a leading BOM if present.
    text = text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    return _rows_to_records(list(reader.fieldnames), list(reader))


# --------------------------------------------------------------------------- #
# Excel (.xlsx / .xlsm via openpyxl, legacy .xls via xlrd)
# --------------------------------------------------------------------------- #
def _stringify_cell(value: Any) -> str:
    """Render an Excel cell value as the trimmed string a CSV would contain."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_xlsx_rows(content: bytes) -> list[list[Any]]:
    try:
        import openpyxl  # noqa: WPS433 (lazy import; optional dependency)
    except ImportError as exc:  # pragma: no cover - surfaced to the user
        raise ValueError(
            "Reading .xlsx files requires the 'openpyxl' package "
            "(add it via requirements.txt)."
        ) from exc
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.active
        return [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _read_xls_rows(content: bytes) -> list[list[Any]]:
    try:
        import xlrd  # noqa: WPS433 (lazy import; optional dependency)
    except ImportError as exc:  # pragma: no cover - surfaced to the user
        raise ValueError(
            "Reading legacy .xls files requires the 'xlrd' package "
            "(add it via requirements.txt)."
        ) from exc
    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(0)
    return [sheet.row_values(r) for r in range(sheet.nrows)]


def parse_excel(content: bytes, filename: str = "") -> list[dict[str, Any]]:
    name = (filename or "").lower()
    is_legacy_xls = name.endswith(".xls") or content[:8].startswith(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    )
    rows = _read_xls_rows(content) if is_legacy_xls else _read_xlsx_rows(content)

    # Drop leading fully-empty rows, then treat the first row as the header.
    rows = [r for r in rows if any(_stringify_cell(c) for c in r)]
    if not rows:
        return []
    headers = [_stringify_cell(c) for c in rows[0]]

    dict_rows: list[dict[str, Any]] = []
    for r in rows[1:]:
        row: dict[str, Any] = {}
        for i, header in enumerate(headers):
            if header:
                row[header] = _stringify_cell(r[i]) if i < len(r) else ""
        dict_rows.append(row)
    return _rows_to_records(headers, dict_rows)


# --------------------------------------------------------------------------- #
# BibTeX
# --------------------------------------------------------------------------- #
def parse_bibtex(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    # Each entry starts with @type{key, ... }
    for entry_match in re.finditer(r"@(\w+)\s*\{", text):
        start = entry_match.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        fields = _parse_bibtex_fields(body)
        if not fields:
            continue
        rec = _blank_record()
        rec["raw"] = fields
        rec["title"] = _clean_bibtex(fields.get("title", ""))
        rec["abstract"] = _clean_bibtex(fields.get("abstract", ""))
        rec["doi"] = _clean_bibtex(fields.get("doi", ""))
        rec["url"] = _clean_bibtex(fields.get("url", ""))
        rec["venue"] = _clean_bibtex(
            fields.get("journal") or fields.get("booktitle") or fields.get("publisher", "")
        )
        rec["year"] = _coerce_year(fields.get("year"))
        authors = _clean_bibtex(fields.get("author", ""))
        rec["authors"] = [a.strip() for a in re.split(r"\s+and\s+", authors) if a.strip()]
        kw = _clean_bibtex(fields.get("keywords", ""))
        rec["keywords"] = [k.strip() for k in re.split(r"[;,]", kw) if k.strip()]
        if any([rec["title"], rec["abstract"], rec["authors"]]):
            records.append(rec)
    return records


def _parse_bibtex_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for m in re.finditer(r"(\w+)\s*=\s*", body):
        key = m.group(1).lower()
        pos = m.end()
        if pos >= len(body):
            break
        ch = body[pos]
        if ch == "{":
            depth = 1
            j = pos + 1
            while j < len(body) and depth > 0:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            fields[key] = body[pos + 1:j - 1]
        elif ch == '"':
            j = pos + 1
            while j < len(body) and body[j] != '"':
                j += 1
            fields[key] = body[pos + 1:j]
        else:
            j = pos
            while j < len(body) and body[j] not in ",}\n":
                j += 1
            fields[key] = body[pos:j].strip()
    return fields


def _clean_bibtex(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def detect_format(filename: str, content: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".ris"):
        return "ris"
    if name.endswith(".bib") or name.endswith(".bibtex"):
        return "bib"
    if name.endswith(".csv") or name.endswith(".tsv"):
        return "csv"
    # Sniff content
    head = content.lstrip("﻿").lstrip()
    if re.match(r"^TY\s{0,2}-", head):
        return "ris"
    if head.startswith("@"):
        return "bib"
    return "csv"


_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _looks_like_excel(name: str, content: bytes) -> bool:
    if name.endswith((".xlsx", ".xlsm", ".xltx", ".xls")):
        return True
    head = content[:8]
    if head.startswith(_XLS_MAGIC):
        return True
    # .xlsx is a zip; only treat zip content as Excel when it clearly holds a
    # workbook, so ordinary .zip uploads aren't misread.
    if head.startswith(_XLSX_MAGIC) and b"xl/" in content[:4000]:
        return True
    return False


def parse_file(filename: str, content: bytes | str) -> list[dict[str, Any]]:
    name = (filename or "").lower()
    if isinstance(content, (bytes, bytearray)):
        content = bytes(content)
        if _looks_like_excel(name, content):
            return parse_excel(content, name)
        text = content.decode("utf-8-sig", errors="replace")
    else:
        text = content
    fmt = detect_format(filename, text)
    if fmt == "ris":
        return parse_ris(text)
    if fmt == "bib":
        return parse_bibtex(text)
    return parse_csv(text)
