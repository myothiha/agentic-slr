# Implementation Plan: Full-Text Extraction for Included Papers

Implement full-text PDF extraction and parsing for "Included" papers. This covers resolving the included paper list (using manual labels or falling back to AI labels), automated downloading of Open Access (OA) papers, manual upload support, folder scanning, and PDF text extraction.

## User Review Required

> [!NOTE]
> **Open Access API Choice:** We will use the **OpenAlex API** (`https://api.openalex.org/works/https://doi.org/<doi>`) to resolve Open Access URLs. It is free, fast, doesn't require an API key for moderate usage, and provides high-quality URLs.
>
> **Library Choice:** We will add `pypdf` to `requirements.txt` for extracting text. It is lightweight, stable, and has no C-extensions or external binary dependencies (unlike PyMuPDF or pdf2image/OCR), which makes it highly portable.
>
> **Separate Text Storage:** The extracted plain text will be stored in individual text files (e.g. `extracted_texts/<index>.txt`) rather than inline inside the central state JSON. This prevents file bloating and speeds up read/write operations.
>
> **Included Papers Choice Logic:** If manual screening is in progress (i.e. the count of user-screened papers where status is `user_confirmed` or `user_modified` does not match the total papers count in the screening state), the system will use the AI-labeled `Include` papers (`llm_label == "Include"`). Once manual screening is fully complete, the system will switch to using only manually labeled `Include` papers (`label == "Include"`).

## Open Questions

None at this stage. The target workflow and design details are fully understood.

---

## Prerequisite Migration: Renumber Screening `03` → `02c`

Before adding the full-text stage, rename the existing screening stage so the pipeline reads
`02b_page_filter → 02c_abstract_title_screening → 03a_full_text_extraction`. The path string is
referenced in only three functional places plus the physical data folder, so this is a clean edit.

*   **[MODIFY] `backend/paths.py`** — change `SCREENING_DIR = DATA_DIR / "03_abstract_title_screening"`
    to `SCREENING_DIR = DATA_DIR / "02c_abstract_title_screening"`. All other code reaches the folder
    through `paths.SCREENING_DIR`, so nothing else needs touching for the path itself.
*   **[MODIFY] `backend/main.py`** (stage manifest, ~line 410) — change the stage `"key"` from
    `"03_abstract_title_screening"` to `"02c_abstract_title_screening"`.
*   **[MODIFY] `backend/screening_service.py`** — update the module docstring reference (line ~5) to the
    new folder name. (The `agents.abstract_title_screening` import is a module name, **not** a path — leave it.)
*   **Move the data folder:** `git mv data/03_abstract_title_screening data/02c_abstract_title_screening`.
*   **Backup caveat:** existing backup zips under `backups/` embed the old `03_abstract_title_screening`
    path. Restoring a pre-migration backup will land data in the old folder name. Either accept that old
    backups predate this change, or add a one-time fallback in the restore path that maps the legacy folder
    to the new name. This does not block the migration.

---

## Proposed Changes

### Backend Dependencies

#### [MODIFY] [requirements.txt](file:///Users/myothiha/Projects/phd_research/agentic-slr/requirements.txt)
*   Add `pypdf==4.2.0` for PDF parsing.
*   Add `httpx==0.27.0` for the OpenAlex API and PDF downloads. **Use the *synchronous* `httpx.Client`
    invoked inside the existing thread-pool pattern (as `tagging_service` already does with `threading`)** —
    do not mix an async client with a thread pool. Send OpenAlex requests with a `mailto=<user email>` query
    param to stay in its polite pool and avoid rate limiting.

---

### Backend Service & Core Logic

#### [MODIFY] [paths.py](file:///Users/myothiha/Projects/phd_research/agentic-slr/backend/paths.py)
*   Define new path constants (note the stage number `03a`, which places full-text extraction
    immediately after screening and before keyword tagging — matching its position in the sidebar nav):
    *   `FULL_TEXT_DIR = DATA_DIR / "03a_full_text_extraction"`
    *   `FULL_TEXT_PDF_DIR = FULL_TEXT_DIR / "raw_pdfs"`
    *   `FULL_TEXT_TXT_DIR = FULL_TEXT_DIR / "extracted_texts"`
    *   `FULL_TEXT_STATE_FILE = FULL_TEXT_DIR / "full_text_state.json"`
*   Add `FULL_TEXT_PDF_DIR` and `FULL_TEXT_TXT_DIR` to the directories created during `ensure_dirs()`.

#### [NEW] [full_text_service.py](file:///Users/myothiha/Projects/phd_research/agentic-slr/backend/full_text_service.py)
Create a new service module to orchestrate PDF downloads, directory scanning, and text extraction:
*   **Included-papers resolution — reuse the existing resolver, do not reimplement it.** The codebase
    already exposes `screening_service.included_papers()` and `screening_service.include_source()`, which
    `tagging_service` and `analysis_service` both consume. The full-text service **must** call these rather
    than re-deriving the Include set from `screening_state.json`, so the full-text page stays consistent
    with keyword tagging and analysis.
    *   `included_papers()` here simply delegates: `return screening_service.included_papers()`.
    *   The dashboard "source" label (Manual vs AI fallback) comes from `screening_service.include_source()`
        (`"user"` / `"ai"` / `"none"`), not a separate `screened_count == total_count` computation.
    *   Rationale: the existing resolver prefers any user `label == "Include"`, otherwise falls back to
        `llm_label == "Include"` **while excluding papers the user overrode to `Exclude`/`Maybe`**. The
        original bespoke logic dropped that override guard, so it would have queued PDFs for papers the user
        explicitly excluded during partial screening. Delegating avoids that bug entirely.
*   `get_state()`: Load or initialize `full_text_state.json`.
*   `save_state(state)`: Write the state to `full_text_state.json` safely with locks.
*   `sync_included_papers()`: Reconcile `full_text_state.json` with the current set of included papers.
    Remove state entries for papers no longer included; create blank entries for newly included ones.
    **Do not hard-delete PDF/TXT files during automatic sync.** Because the Include set legitimately shifts
    while the user is still screening, a paper can drop out and come back — silently deleting a manually
    uploaded PDF would lose user work. Instead, leave the files in place (or move them to an
    `raw_pdfs/_archived/` subfolder) and only purge on an explicit user action (the `DELETE` route below).
*   `auto_download_oa(index)`: Query the OpenAlex API using the paper's DOI (with the `mailto=` param). Read
    the OA PDF URL from `best_oa_location.pdf_url` (fall back to `open_access.oa_url`). If a link is found,
    fetch the PDF, save it to `raw_pdfs/<index>.pdf`, extract its text, and mark status `extracted`.
*   `auto_download_oa_batch()`: Run OA checks in a thread pool for all papers with `status == "missing"` and
    an available DOI. (Of the current 270 AI-Include papers, 258 have a DOI.)
*   `extract_text_from_pdf(index)`: Given a PDF at `raw_pdfs/<index>.pdf`, extract text from all pages using
    `pypdf`. Save the full text to `extracted_texts/<index>.txt`. Update metadata (preview, text length) in
    `full_text_state.json`. **If extraction yields empty or near-empty text (e.g. < 100 chars), set status
    `error` with a reason like `"no_text_layer"`, not `extracted`** — `pypdf` has no OCR, so scanned /
    image-only PDFs produce no text and must not be reported as successful.
*   `get_extracted_text(index)`: Helper to read the plain text file from `extracted_texts/<index>.txt`.
*   `scan_local_pdfs()`: Scan `data/03a_full_text_extraction/raw_pdfs/` for any files named `<index>.pdf`. If found, extract text and update the state. This enables manual dragging and dropping of files directly into the filesystem.
*   `save_uploaded_pdf(index, file_bytes)`: Write uploaded PDF bytes to `raw_pdfs/<index>.pdf` and extract text.

---

### Backend API Routing

#### [MODIFY] [main.py](file:///Users/myothiha/Projects/phd_research/agentic-slr/backend/main.py)
*   Import the new `full_text_service`.
*   (From the prerequisite migration) update the screening stage `"key"` to `"02c_abstract_title_screening"`,
    and optionally add a `"03a_full_text_extraction"` entry to the stage manifest so the dashboard progress
    tracker reflects the new stage.
*   Register the following new API routes:
    *   `GET /api/full-text`: Reconciles state and returns the current dashboard payload (list of included papers with their extraction status, counts, and paths).
    *   `GET /api/full-text/papers/{index}/text`: Returns the plain text content of a specific paper from its individual `.txt` file.
    *   `POST /api/full-text/auto-download`: Triggers batch Open Access downloader in the background.
    *   `POST /api/full-text/scan`: Triggers a local directory scan for manually dropped PDFs.
    *   `POST /api/full-text/upload/{index}`: Receives a multipart file upload, saves it to `raw_pdfs/`, and triggers text extraction.
    *   `DELETE /api/full-text/papers/{index}`: Deletes the raw PDF file, the extracted text file, and resets the paper's extraction state to `missing`.

---

### Frontend Client & Routing

#### [MODIFY] [api.js](file:///Users/myothiha/Projects/phd_research/agentic-slr/frontend/src/api.js)
Add wrapper functions for the new backend routes:
*   `api.getFullText()`
*   `api.getPaperText(index)`
*   `api.triggerAutoDownload()`
*   `api.scanLocalPdfs()`
*   `api.uploadPdf(index, file)`
*   `api.deletePdf(index)`

#### [MODIFY] [App.jsx](file:///Users/myothiha/Projects/phd_research/agentic-slr/frontend/src/App.jsx)
*   Import the new `FullTextExtraction` page.
*   Add `"Full-Text Extraction"` to the `nav` list in the sidebar (inserting it between "Abstract/Title Screening" and "Keyword Extraction").
*   Add a route for `/full-text` mapping to `<FullTextExtraction />`.

---

### Frontend Components & Dashboard UI

#### [NEW] [FullTextExtraction.jsx](file:///Users/myothiha/Projects/phd_research/agentic-slr/frontend/src/pages/FullTextExtraction.jsx)
Build a dashboard view matching the rest of the application's clean design system:
*   **Header & Stats Section:** Display visual cards showing:
    *   *Total Included:* Total number of papers currently marked for full-text extraction.
    *   *Source Type:* Display whether the paper list is resolved from "Manual screening (Complete)" or "AI predictions (In-progress fallback)".
    *   *Extracted:* Count of papers with successfully extracted full text.
    *   *Pending:* Count of papers missing a PDF.
    *   *Errors:* Count of papers that failed parsing.
*   **Control Panel:**
    *   **Auto-Download Open Access** button (with loading spinner and status feedback).
    *   **Scan Local PDF Directory** button (useful if files were dropped directly in the filesystem).
*   **Paper Grid / Table:** A filterable list of included papers. Columns:
    *   `Index` and `Title` (with DOI link if available).
    *   `Source Database` (IEEE, ACM, Scopus, etc.).
    *   `Status Badge` (Green: Extracted, Blue: Downloading, Gray: Missing, Red: Error — include the
        `no_text_layer` case so scanned PDFs surface as an actionable error rather than silent success).
    *   `Actions`:
        *   If `missing`: Direct URL link to download (opens in new tab) + file upload drag zone/button.
        *   If `extracted`: Clickable "Preview Text" button (opens a modal/collapsible showing extracted text statistics and fetches the first 1000 characters from `/api/full-text/papers/{index}/text`) + "Delete/Reset" button.
*   **Upload Area:** Integrates a simple drop zone for files or single-file file picker.

---

## Verification Plan

### Automated Tests
*   Run FastAPI app and inspect endpoint contracts in `/docs` (Swagger UI).
*   Test Open Access downloader locally with a known open-access paper DOI (e.g., `10.1109/ACDSA65407.2025.11166422` from raw CSV records) to verify download and text parsing.
*   Test local directory scanning by adding a sample PDF to `data/03a_full_text_extraction/raw_pdfs/` and triggering the scan.

### Migration Verification
*   After renaming, confirm the app still loads screening data from `data/02c_abstract_title_screening/`
    and that the dashboard stage tracker shows the screening stage under its new key.

### Manual Verification
*   Confirm the dashboard "source" label reflects `screening_service.include_source()` — Manual (user) when
    any paper is user-labelled Include, AI fallback otherwise — and matches the count shown on the keyword
    tagging page for the same data.
*   Verify PDF uploads via the UI dropzone.
*   Verify that extracted text previews correctly show the parsed PDF text layout, ensuring title and body text are readable.
*   Verify a scanned/image-only PDF is reported as `error` (`no_text_layer`), not `extracted`.
*   Verify that separate `.txt` files are written in `data/03a_full_text_extraction/extracted_texts/` and that the central `full_text_state.json` file remains small and readable.
