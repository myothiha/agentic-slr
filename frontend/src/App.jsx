import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import DatabaseManagement from "./pages/DatabaseManagement.jsx";
import ContextConfiguration from "./pages/ContextConfiguration.jsx";
import DataIngestion from "./pages/DataIngestion.jsx";

const nav = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/context", label: "Context Configuration" },
  { to: "/databases", label: "Database Management" },
  { to: "/ingestion", label: "Data Ingestion" },
];

function Sidebar() {
  return (
    <aside className="w-64 shrink-0 bg-slate-900 text-slate-200 min-h-screen p-5">
      <div className="mb-8">
        <h1 className="text-lg font-semibold text-white">Agentic SLR</h1>
        <p className="text-xs text-slate-400 mt-1">Systematic Literature Review</p>
      </div>
      <nav className="space-y-1">
        {nav.map((n) => (
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
      </nav>
      <div className="mt-8 border-t border-slate-700 pt-4">
        <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">Pipeline</p>
        <ol className="space-y-1 text-xs text-slate-400">
          <li>1. Context &amp; Ingestion</li>
          <li className="opacity-50">2. Deduplication</li>
          <li className="opacity-50">3. Screening</li>
        </ol>
      </div>
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
          <Route path="/ingestion" element={<DataIngestion />} />
        </Routes>
      </main>
    </div>
  );
}
