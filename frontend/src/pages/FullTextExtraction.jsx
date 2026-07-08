import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

const STATUS_STYLE = {
  extracted: "bg-green-100 text-green-700",
  downloading: "bg-blue-100 text-blue-700",
  missing: "bg-slate-100 text-slate-600",
  error: "bg-red-100 text-red-700",
};

const SOURCE_LABEL = {
  user: "Manual screening (complete)",
  ai: "AI predictions (in-progress fallback)",
  none: "No included papers yet",
};

const ERROR_HINT = {
  no_text_layer: "No text layer — scanned/image PDF (needs OCR)",
  no_doi: "No DOI available for auto-download",
  no_oa_pdf: "No open-access PDF found",
  not_a_pdf: "Downloaded file was not a PDF",
  pdf_missing: "PDF file is missing",
};

export default function FullTextExtraction() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [statusView, setStatusView] = useState("all");
  const [busy, setBusy] = useState(null); // "download" | "scan" | null
  const [note, setNote] = useState(null);
  const [preview, setPreview] = useState(null); // { index, text, char_count }
  const [perPage, setPerPage] = useState(20);
  const [page, setPage] = useState(1);

  const load = () =>
    api.getFullText().then(setData).catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    setPage(1);
  }, [statusView, perPage]);

  const papers = data?.papers || [];
  const filtered = useMemo(
    () => (statusView === "all" ? papers : papers.filter((p) => p.status === statusView)),
    [papers, statusView]
  );

  if (error) return <ErrorBox message={error} />;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  const c = data.counts || {};
  const source = data.include_source || "none";

  if (c.total === 0) {
    return (
      <div>
        <h2 className="text-2xl font-semibold text-slate-900 mb-4">Full-Text Extraction</h2>
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          No included papers yet. Label papers as <strong>Include</strong> in{" "}
          <Link to="/screening" className="text-blue-600 hover:underline">
            screening
          </Link>{" "}
          first.
        </div>
      </div>
    );
  }

  const runAction = async (kind, fn) => {
    setBusy(kind);
    setNote(null);
    try {
      const res = await fn();
      await load();
      if (kind === "download") {
        setNote(
          `Auto-download: ${res.extracted} extracted, ${res.failed} failed of ${res.attempted} attempted.`
        );
      } else if (kind === "scan") {
        setNote(`Scan: ${res.extracted} extracted from ${res.scanned} local PDF(s).`);
      }
    } catch (e) {
      setNote(`Error: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const upload = async (index, file) => {
    if (!file) return;
    setNote(null);
    try {
      await api.uploadPdf(index, file);
      await load();
    } catch (e) {
      setNote(`Upload failed for ${index}: ${e.message}`);
    }
  };

  const remove = async (index) => {
    try {
      await api.deletePdf(index);
      await load();
    } catch (e) {
      setNote(`Delete failed for ${index}: ${e.message}`);
    }
  };

  const openPreview = async (index) => {
    try {
      setPreview({ index, text: "Loading…", char_count: null });
      const res = await api.getPaperText(index);
      setPreview(res);
    } catch (e) {
      setPreview({ index, text: `Error: ${e.message}`, char_count: null });
    }
  };

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * perPage;
  const pageItems = filtered.slice(start, start + perPage);

  return (
    <div>
      <header className="mb-4">
        <h2 className="text-2xl font-semibold text-slate-900">Full-Text Extraction</h2>
        <p className="text-slate-500 mt-1">
          Download or upload PDFs for the included papers and extract their full text for{" "}
          <Link to="/tagging" className="text-blue-600 hover:underline">
            keyword tagging
          </Link>
          .
        </p>
      </header>

      {/* Stats */}
      <div className="mb-4 grid grid-cols-4 gap-4">
        <Stat label="Total Included" value={c.total} onClick={() => setStatusView("all")} active={statusView === "all"} />
        <Stat label="Extracted" value={c.extracted} tone="text-green-600" onClick={() => setStatusView("extracted")} active={statusView === "extracted"} />
        <Stat label="Pending" value={c.missing} tone="text-slate-600" onClick={() => setStatusView("missing")} active={statusView === "missing"} />
        <Stat label="Errors" value={c.error} tone="text-red-600" onClick={() => setStatusView("error")} active={statusView === "error"} />
      </div>

      <div className="mb-5 rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-600">
        Source of included set: <strong>{SOURCE_LABEL[source]}</strong>
      </div>

      {/* Controls */}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-4">
        <button
          onClick={() => runAction("download", api.triggerAutoDownload)}
          disabled={busy !== null}
          className="btn-primary"
        >
          {busy === "download" ? "Downloading…" : "Auto-Download Open Access"}
        </button>
        <button
          onClick={() => runAction("scan", api.scanLocalPdfs)}
          disabled={busy !== null}
          className="btn-secondary"
        >
          {busy === "scan" ? "Scanning…" : "Scan Local PDF Directory"}
        </button>
        <span className="text-xs text-slate-400">
          Drop files named <code className="font-mono">&lt;index&gt;.pdf</code> into
          data/03a_full_text_extraction/raw_pdfs/ then scan.
        </span>
        {note && <span className="ml-auto text-sm text-slate-700">{note}</span>}
      </div>

      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {statusView === "all" ? "All papers" : `Status: ${statusView}`} · {total} shown
        </p>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Per page
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
            value={perPage}
            onChange={(e) => setPerPage(Number(e.target.value))}
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-3">Index</th>
              <th className="px-3 py-3">Title</th>
              <th className="px-3 py-3">Database</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.map((p) => (
              <tr key={p.index} className="align-top">
                <td className="px-3 py-3 font-mono text-xs text-slate-500 whitespace-nowrap">
                  {p.index}
                </td>
                <td className="px-3 py-3 text-slate-800">
                  {p.title || "(no title)"}
                  {p.doi && (
                    <a
                      href={`https://doi.org/${p.doi}`}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-2 text-xs text-blue-600 hover:underline"
                    >
                      DOI ↗
                    </a>
                  )}
                </td>
                <td className="px-3 py-3 text-slate-600 whitespace-nowrap">{p.database || "—"}</td>
                <td className="px-3 py-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[p.status]}`}>
                    {p.status}
                  </span>
                  {p.status === "extracted" && (
                    <span className="ml-1 text-xs text-slate-400">
                      {p.char_count?.toLocaleString()} chars
                    </span>
                  )}
                  {p.status === "error" && (
                    <div className="mt-1 text-xs text-red-500">
                      {ERROR_HINT[p.error] || p.error}
                    </div>
                  )}
                </td>
                <td className="px-3 py-3">
                  <PaperActions
                    paper={p}
                    onUpload={(f) => upload(p.index, f)}
                    onPreview={() => openPreview(p.index)}
                    onDelete={() => remove(p.index)}
                  />
                </td>
              </tr>
            ))}
            {total === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-slate-400">
                  No papers in this view.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <p className="text-slate-500">
            Showing {start + 1}–{start + pageItems.length} of {total}
          </p>
          <div className="flex items-center gap-1">
            <PageBtn disabled={current <= 1} onClick={() => setPage(1)}>« First</PageBtn>
            <PageBtn disabled={current <= 1} onClick={() => setPage(current - 1)}>‹ Prev</PageBtn>
            <span className="px-3 text-slate-600">Page {current} of {totalPages}</span>
            <PageBtn disabled={current >= totalPages} onClick={() => setPage(current + 1)}>Next ›</PageBtn>
            <PageBtn disabled={current >= totalPages} onClick={() => setPage(totalPages)}>Last »</PageBtn>
          </div>
        </div>
      )}

      {preview && <PreviewModal preview={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function PaperActions({ paper, onUpload, onPreview, onDelete }) {
  const fileRef = useRef(null);
  const isExtracted = paper.status === "extracted";
  const hasPdf = isExtracted || paper.status === "downloading";

  return (
    <div className="flex flex-wrap items-center gap-1">
      {isExtracted ? (
        <>
          <button
            onClick={onPreview}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
          >
            Preview Text
          </button>
          <button
            onClick={onDelete}
            className="rounded border border-red-300 bg-white px-2 py-0.5 text-xs text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </>
      ) : (
        <>
          {(paper.download_url || paper.pdf_url) && (
            <a
              href={paper.download_url || paper.pdf_url}
              target="_blank"
              rel="noreferrer"
              title={paper.download_url || paper.pdf_url}
              className="rounded border border-blue-300 bg-white px-2 py-0.5 text-xs text-blue-600 hover:bg-blue-50"
            >
              Download ↗
            </a>
          )}
          <button
            onClick={() => fileRef.current?.click()}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
          >
            Upload PDF
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => {
              onUpload(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {hasPdf && (
            <button
              onClick={onDelete}
              className="rounded border border-red-300 bg-white px-2 py-0.5 text-xs text-red-600 hover:bg-red-50"
            >
              Reset
            </button>
          )}
        </>
      )}
    </div>
  );
}

function PreviewModal({ preview, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <span className="font-mono text-sm text-slate-500">{preview.index}</span>
            {preview.char_count != null && (
              <span className="ml-2 text-xs text-slate-400">
                {preview.char_count.toLocaleString()} chars total
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            ✕
          </button>
        </div>
        <div className="max-h-[65vh] overflow-y-auto p-4">
          <pre className="whitespace-pre-wrap break-words font-sans text-sm text-slate-700">
            {(preview.text || "").slice(0, 5000)}
            {(preview.text || "").length > 5000 && "\n\n… (truncated preview)"}
          </pre>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, tone = "text-slate-900", onClick, active }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-4 text-left ${
        active ? "border-blue-400 ring-1 ring-blue-300" : "border-slate-200"
      } bg-white hover:bg-slate-50`}
    >
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${tone}`}>{value ?? 0}</p>
    </button>
  );
}

function PageBtn({ disabled, onClick, children }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}
