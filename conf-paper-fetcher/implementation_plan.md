# Independent Conference Paper Fetcher Plan

Create a fully isolated, standalone Python service named `conf-paper-fetcher` inside its own folder. This service runs its own web server to expose an API and serves a built-in web portal for querying, enriching, and downloading paper lists from DBLP and Semantic Scholar.

> [!NOTE]
> **Scope Restriction:** We will focus **strictly** on the `conf-paper-fetcher` folder. No files inside the parent `agentic-slr` project will be modified.

---

## User Review Required

> [!IMPORTANT]
> **Self-Contained Web Portal & API:** The `conf-paper-fetcher` folder will contain a complete, independent service:
> - A Python HTTP server (`server.py`) serving a web portal at `/` and exposing an API at `/api/fetch`.
> - A frontend interface (`index.html`) with input fields for conferences, keywords, and year ranges.
>
> **Zero External Dependencies:** Built using Python's standard library (e.g. `http.server`, `urllib.request`) and vanilla HTML/CSS/JS. No external packages (like FastAPI, Flask, or React) are required.

---

## Proposed Changes

All files will be created inside the new subdirectory `conf-paper-fetcher`.

### Independent Service Components

#### [NEW] [fetcher.py](file:///Users/myothiha/Projects/phd_research/agentic-slr/conf-paper-fetcher/fetcher.py)
Core paper retrieval and enrichment engine.
- Queries DBLP using optimized Boolean queries (filtering by conference and keywords).
- Queries Semantic Scholar by DOI/Title to fetch missing abstracts.
- Returns a list of parsed and unified paper records.

#### [NEW] [server.py](file:///Users/myothiha/Projects/phd_research/agentic-slr/conf-paper-fetcher/server.py)
A standard-library-based HTTP server to serve both the frontend and backend API.
- Serves static portal files (e.g. `index.html`) on `GET /`.
- Exposes `POST /api/fetch` which accepts JSON configs and runs the fetcher.
- Exposes `GET /health` for status check.
- Configurable port via CLI argument `--port`.

#### [NEW] [index.html](file:///Users/myothiha/Projects/phd_research/agentic-slr/conf-paper-fetcher/index.html)
A single-page web portal with premium modern aesthetics:
- Input fields to add conferences one-by-one (displayed as clickable tags).
- Keyword list inputs.
- Start and end year selectors.
- Fetch status indicator (loading spinner, logs, success messages).
- Search results grid displaying title, venue, year, abstract, and links.
- Download buttons to save the fetched results as a JSON or BibTeX file.

#### [NEW] [README.md](file:///Users/myothiha/Projects/phd_research/agentic-slr/conf-paper-fetcher/README.md)
Instructions on how to copy, launch, and use the independent service on any system.

---

## Verification Plan

### Manual Verification
1. Start the service locally:
   ```bash
   python3 conf-paper-fetcher/server.py --port 8080
   ```
2. Navigate to `http://localhost:8080` in the browser.
3. Verify that the web portal renders correctly.
4. Input:
   - Conference: `ICML` (add to list)
   - Keywords: `commerce`
   - Year Range: `2024` to `2024`
5. Click **Fetch Papers**.
6. Check that the loader appears and after retrieval:
   - The paper list is populated inside a table in the portal.
   - You can read abstracts and see DOI links.
7. Click **Download JSON** and check that the downloaded file contains the correct papers with abstract fields.
8. Copy the entire `conf-paper-fetcher` directory outside the project workspace and run it there to verify complete portability.
