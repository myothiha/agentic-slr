# Project Overview

This project aims to semi-automate the agentic workflow for the Systematic Literature Review (SLR) process.

A web interface (built with React and FastAPI) will be implemented to support the following user journey:

## 1. Context Configuration & Database Management
- **Database Management**: View, add, and edit target data sources (defaults: IEEE Xplore, Scopus, Web of Science, ACM Digital Library).
- **Empty paper list**: Each database row has an "Empty" action that clears that database's ingested papers while keeping the database itself. The user is prompted to choose between emptying papers only, or a cascade reset that also clears the downstream deduplication, page-filter, and screening results derived from those papers.
- **Context Configuration**: A web form to receive the SLR metadata: Title, Research Questions, a complex Boolean keyword string, and structured inclusion/exclusion criteria.
- **Dynamic Highlighting**: An agent converts the keyword string into deterministic matching rules to automatically highlight relevant keywords across papers in the UI.

## 2. Data Ingestion
- An upload form to ingest lists of papers extracted from multiple databases. 
- If multiple files are uploaded for a single database, they are combined into one unified dataset for that database.
- The raw data is converted into a uniform **JSON format** (one file per database) and each paper is given a sequential index (e.g., `IEEE-001`) for traceability.
- **Retain original files**: The original uploaded files (CSV, Excel, etc.) are also kept on the server (only the latest upload batch per database is retained) and can be downloaded again from the per-database raw paper page.

## 3. Deduplication Process
- **Intra-database deduplication**: Remove duplicates within a single database if multiple files were uploaded.
- **Inter-database deduplication**: Deduplicate across multiple databases enforcing priority (e.g., start with IEEE, then remove duplicates from ACM, then Scopus, then Web of Science).
- **Traceability**: Compute a deduplication matrix showing exactly how many papers were removed from each database due to duplication. The process must be step-by-step and traceable, showing original matched papers and allowing users to restore mistakenly removed papers. 
- The final deduplicated dataset is explicitly saved into a new stage folder to maintain an unmodified original list.

## 4. Abstract / Title Screening
- Users can screen the deduplicated list database by database.
- **Screening Interface**: A side-by-side view displaying the paper (Title, Abstract, Year, Keywords) next to the inclusion/exclusion criteria. Text matching the context keywords will be visually highlighted.
- **LLM Agent (Powered by LangChain)**: An AI agent reads the title, abstract, and keywords, compares them against the criteria, and generates reasoning alongside a suggested label (Include, Exclude, Maybe).
- **User Review**: Users can override the LLM's label and add their own comments. The system tracks the modification trail (e.g., "LLM labeled", "User confirmed", or "User modified").
- **Review Page**: A dedicated, color-coded list view (Green/Red/Yellow) displaying all previously screened papers, allowing users to seamlessly edit labels inline without refreshing the page.

## File Structure

At the highest level, the project uses the following folders:
- `context/`: Stores all global configurations like `metadata.json` (research questions, criteria, keyword rules, and databases).
- `agents/`: Contains the LangChain-powered agents and tools for highlighting, deduplication, and screening.
- `data/`: Contains all data related to the SLR process. We always create a new folder for each distinct SLR pipeline step (e.g., `01_raw_paper_list`, `02_deduplication`, `03_abstract_title_screening`) to ensure traceability and avoid modifying original files.
