# Keyword Analysis — Plan (Phase 6)

A new **Keyword Analysis** page for exploring the tag data via configurable,
multi-level charts, with saveable named views.

## Data it builds on
- Unified papers store: `papers[i].tags[<dimension field>] = [tags…]`, plus
  `year` and `database` per paper.
- Per-dimension **categories** (groups) already defined on the Grouping page;
  ungrouped tags act as standalone categories.

## Model: levels (small multiples)
A **view** has up to three ordered levels. **Eligible dimension for any level =
any tag dimension (E-commerce Task, LLM Technique, …) or Publication Year.**
The three levels should be distinct dimensions.

1. **Top level — Panels.** User multi-selects values of this dimension. Each
   selected value renders its **own diagram** (small multiples).
   - Example: top = E-commerce Task, select {recommendation, search} → two
     diagrams, one per task.
2. **Second level — Breakdown (X-axis).** Within each diagram, bars show the
   distribution over this dimension's values, restricted to papers matching that
   diagram's top-level value.
   - Example: second = LLM Technique → each diagram shows the LLM-technique
     distribution for its task.
3. **Third level — Series (optional).** If set, each bar is split by this
   dimension's values (stacked or grouped bars), adding a dimension to every
   diagram.
   - Example: third = Year → each LLM-technique bar is split by year.

**Unit (tag dimensions only):** choose **category** (default) or **raw tag** as
the values for that level. Publication Year uses years directly (with optional
bucketing later).

## Counting semantics (tags are many-to-many)
- A paper matches a panel value if it carries that tag/category (or `year == v`).
- Within a level's multi-select: **OR**. Across the panel→breakdown→series
  chain: **AND**.
- Breakdown/series bars count papers per value; a paper with two tags on an axis
  adds to two bars, so bar sums can exceed the distinct paper count. The UI shows
  both the distinct paper count and the bar sum. Year is single-valued and sums
  cleanly.

## Matching-papers list
- Under the charts, a **"Matching papers"** panel lists every paper in the
  current selection (paginated, with a search box).
- Clicking a bar/segment narrows the list to the papers behind it; a "clear"
  chip resets it.
- Rows show index, title, year, database, and the paper's tags for the in-play
  dimensions (evidence available on expand, reusing the extraction display).
- CSV export of the matching papers (with their in-play tags).

## Saved views (named sub-pages)
- Each configuration is saved as a **named sub-page** under
  `/analysis/:viewId`, listed in a sub-nav, with New / Rename / Delete.
- A view stores the level config, selected values, and display options, so
  reopening restores both the charts and the paper list.

## Backend
- New `backend/analysis_service.py` computing, from a level config:
  for each selected top value → its breakdown bars (and optional series),
  plus the filtered paper indices per bar/segment.
- New state file `data/05_keyword_analysis/analysis_views.json` for saved views.
- Endpoints:
  - `GET  /api/analysis/dimensions` — eligible dimensions + their
    categories/tags + the year range (to populate selectors).
  - `POST /api/analysis/compute` — a config → chart data + matching papers
    (paginated) + per-bar paper indices.
  - `GET/POST/PUT/DELETE /api/analysis/views` — saved-view CRUD.

## Chart type (per view)
The user picks the **basic graph type** for a view; the offered types depend on
how many levels are configured:
- **2 levels (panel value → breakdown):** bar chart (vertical/horizontal),
  **pie / donut**, lollipop, treemap. (Line/area when the breakdown is Year, for
  a trend.)
- **3 levels (+ series):** stacked bar, grouped bar, 100%-stacked bar, or
  **heatmap** (breakdown × series matrix). Pie is disabled here since it can't
  carry a third dimension.
The chosen type is saved with the view. Each small-multiple panel uses the same
type. The UI only shows types compatible with the current level count.

## Frontend
- Nav item **Keyword Analysis** + sub-nav of saved views + "New view".
- **View editor:** level 1/2/3 dimension pickers (level 3 optional), unit
  toggle per tag level, multi-select of top-level values, and a **chart-type
  selector** (see above).
- **Charts:** a grid of small-multiple diagrams (one per top value), rendered in
  the selected chart type.
- **Options:** counts vs %, min-count / top-N (hide the many count-1 tags),
  category vs raw tag.
- **Matching-papers** panel as above.

## Additional ideas (optional)
- **Heatmap** alternative for the 3-level case (breakdown × series matrix per
  panel), good for co-occurrence.
- **Trend-over-time** line chart when Year is the breakdown/series.
- **Comparison mode** — pin two panels side by side.
- **PNG export** of a chart for the thesis.

## Phasing
1. **Phase 1:** 2 levels (panels → breakdown bars), multi-select top values,
   matching-papers list (paginated + search + CSV), counts/% + min-count,
   category-vs-tag, save/name views as sub-pages.
2. **Phase 2:** optional third level (series: stacked/grouped), bar-click →
   narrow the paper list, evidence drill-down.
3. **Phase 3:** heatmap, trend-over-time, comparison mode, PNG export.

## Charting library
Because the view now supports several chart types (bar, pie/donut, stacked,
grouped, heatmap, line), a chart library is the practical choice.
**Recommendation: add `recharts`** (already listed as an allowed artifact lib in
this project) — it covers all of these with tooltips/legends and far less code
than hand-rolling each type. Heatmap would be a small custom SVG on top.

## Decisions needed before building
1. Default breakdown unit: **category vs raw tag**.
2. Confirm adding **recharts** for the configurable chart types (recommended).
