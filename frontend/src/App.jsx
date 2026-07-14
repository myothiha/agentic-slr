import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import DatabaseManagement from "./pages/DatabaseManagement.jsx";
import ContextConfiguration from "./pages/ContextConfiguration.jsx";
import DataIngestion from "./pages/DataIngestion.jsx";
import DatabasePapers from "./pages/DatabasePapers.jsx";
import Deduplication from "./pages/Deduplication.jsx";
import DeduplicatedList from "./pages/DeduplicatedList.jsx";
import PageFilter from "./pages/PageFilter.jsx";
import Screening from "./pages/Screening.jsx";
import ScreenedReview from "./pages/ScreenedReview.jsx";
import FullTextExtraction from "./pages/FullTextExtraction.jsx";
import KeywordExtraction from "./pages/KeywordExtraction.jsx";
import KeywordGrouping from "./pages/KeywordGrouping.jsx";
import KeywordAnalysis from "./pages/KeywordAnalysis.jsx";
import AnalysisPapers from "./pages/AnalysisPapers.jsx";
import Backup from "./pages/Backup.jsx";

const navGroups = [
  {
    heading: "Overview",
    items: [
      { to: "/", label: "Dashboard", end: true },
      { to: "/context", label: "Context Configuration" },
    ],
  },
  {
    heading: "Data Sources",
    items: [
      { to: "/databases", label: "Database Management" },
      { to: "/ingestion", label: "Data Ingestion" },
    ],
  },
  {
    heading: "Processing",
    items: [
      { to: "/deduplication", label: "Deduplication" },
      { to: "/page-filter", label: "Page Filter" },
      { to: "/screening", label: "Abstract/Title Screening", end: true },
      { to: "/screening/review", label: "Screened Review" },
      { to: "/full-text", label: "Full-Text Extraction" },
    ],
  },
  {
    heading: "Analysis",
    items: [
      { to: "/tagging", label: "Keyword Extraction", end: true },
      { to: "/tagging/groups", label: "Keyword Grouping" },
      { to: "/analysis", label: "Keyword Analysis" },
    ],
  },
  {
    heading: "System",
    items: [{ to: "/backup", label: "Backup & Restore" }],
  },
];

function Sidebar() {
  return (
    <aside className="w-64 shrink-0 bg-slate-900 text-slate-200 min-h-screen p-5">
      <div className="mb-8">
        <h1 className="text-lg font-semibold text-white">Agentic SLR</h1>
        <p className="text-xs text-slate-400 mt-1">Systematic Literature Review</p>
      </div>
      <nav className="space-y-5">
        {navGroups.map((g) => (
          <div key={g.heading}>
            <p className="px-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {g.heading}
            </p>
            <div className="space-y-1 border-l border-slate-700 ml-3 pl-2">
              {g.items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    `block rounded-md px-3 py-2 text-sm font-medium transition ${
                      isActive
                        ? "bg-blue-600 text-white"
                        : "text-slate-300 hover:bg-slate-800 hover:text-white"
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}

export default function App() {
  return (
    <div className="flex">
      <Sidebar />
      <main className="flex-1 min-h-screen p-8 max-w-6xl">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/context" element={<ContextConfiguration />} />
          <Route path="/databases" element={<DatabaseManagement />} />
          <Route path="/databases/:id" element={<DatabasePapers />} />
          <Route path="/ingestion" element={<DataIngestion />} />
          <Route path="/deduplication" element={<Deduplication />} />
          <Route path="/deduplication/papers" element={<DeduplicatedList />} />
          <Route path="/page-filter" element={<PageFilter />} />
          <Route path="/screening" element={<Screening />} />
          <Route path="/screening/review" element={<ScreenedReview />} />
          <Route path="/full-text" element={<FullTextExtraction />} />
          <Route path="/tagging" element={<KeywordExtraction />} />
          <Route path="/tagging/groups" element={<KeywordGrouping />} />
          <Route path="/analysis" element={<KeywordAnalysis />} />
          <Route path="/analysis/papers" element={<AnalysisPapers />} />
          <Route path="/backup" element={<Backup />} />
        </Routes>
      </main>
    </div>
  );
}
