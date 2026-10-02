import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Download, Loader2, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import type { CsvReject, CsvRun, RerunPolicy } from "@/lib/api/csv-bml";
import { cn } from "@/lib/cn";

const PAGE = 50;

/** CSV files / rows of an upload job that were not loaded, with re-run actions. Renders nothing when clean. */
export function CsvIssues(
  { jobId, workspaceId, onChanged }: { jobId: string; workspaceId: number; onChanged: () => void },
) {
  const [runs, setRuns] = useState<CsvRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRuns(await api.listCsvRuns(workspaceId, jobId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load CSV issues");
    }
  }, [jobId, workspaceId]);
  useEffect(() => { load(); }, [load]);

  if (error) {
    return <div className="border-t border-navy-100 px-4 py-2 text-[11px] text-subtle">CSV issues unavailable: {error}</div>;
  }
  if (!runs || runs.length === 0) return null;
  return (
    <div className="border-t border-navy-100 bg-amber-50/40 px-4 py-3">
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-amber-700">
        <AlertTriangle size={11} /> CSV issues
      </div>
      <ul className="space-y-2">
        {runs.map((r) => (
          <RunIssue key={r.run_id} run={r} workspaceId={workspaceId}
                    onChanged={() => { load(); onChanged(); }} />
        ))}
      </ul>
    </div>
  );
}

function RunIssue(
  { run, workspaceId, onChanged }: { run: CsvRun; workspaceId: number; onChanged: () => void },
) {
  const [open, setOpen] = useState(false);
  const [rejects, setRejects] = useState<CsvReject[]>([]);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [policy, setPolicy] = useState<RerunPolicy>("reject");

  const loadRejects = useCallback(async (offset: number) => {
    const page = await api.getCsvRejects(run.run_id, workspaceId, undefined, offset, PAGE);
    setRejects((prev) => (offset === 0 ? page : [...prev, ...page]));
    setMore(page.length === PAGE);
  }, [run.run_id, workspaceId]);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && run.reject_stored > 0 && rejects.length === 0) {
      try { await loadRejects(0); } catch (e) { setProblem(msg(e)); }
    }
  };

  const act = async (name: string, fn: () => Promise<string>) => {
    setBusy(name); setProblem(null); setNotice(null);
    try {
      setNotice(await fn());
      onChanged();
      if (open && run.reject_stored > 0) await loadRejects(0);
    } catch (e) {
      setProblem(msg(e));
    } finally {
      setBusy(null);
    }
  };

  const rerunRows = () => act("rows", async () => {
    const r = await api.rerunCsvRejects(run.run_id, workspaceId, policy);
    return `Inserted ${r.inserted}`
      + (r.truncated ? ` (${r.truncated} truncated)` : "")
      + `, still rejected ${r.still_rejected}`
      + (r.not_rerunnable ? `, ${r.not_rerunnable} need correcting in the file` : "") + ".";
  });
  const rerunFile = () => act("file", async () => {
    const r = await api.rerunCsvFile(run.run_id, workspaceId);
    return `Re-run started as job ${r.job_id.slice(0, 8)}…`;
  });
  const download = () => act("download", async () => {
    const blob = await api.downloadCsvRejects(run.run_id, workspaceId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${run.table_name ?? "rejects"}_rejects.csv`;
    a.click();
    URL.revokeObjectURL(url);
    return "Downloaded.";
  });

  const fileLevel = run.status !== "loaded";
  const resolved = run.state !== "open";
  const openRows = run.open_rejects;
  return (
    <li className={cn("rounded-lg border bg-white", resolved ? "border-navy-100 opacity-70" : "border-amber-200")}>
      <button type="button" onClick={toggle} className="focus-ring flex w-full items-start gap-2 rounded-lg p-2.5 text-left">
        {open ? <ChevronDown size={12} className="mt-0.5 text-subtle" /> : <ChevronRight size={12} className="mt-0.5 text-subtle" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="truncate text-[12px] font-semibold text-navy-900">{run.source_file}</span>
            {run.table_name && <span className="font-mono text-[10px] text-subtle">→ {run.table_name}</span>}
            <span className={cn(
              "rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
              fileLevel ? "bg-rose-50 text-rose-700" : "bg-amber-100 text-amber-800",
            )}>{fileLevel ? run.status : "partly loaded"}</span>
            {resolved && <span className="text-[10px] text-subtle">{run.state}</span>}
          </div>
          <div className="mt-0.5 text-[11px] text-navy-700">
            {fileLevel
              ? (run.message ?? run.error_code ?? "Not loaded")
              : `${run.rows_loaded} loaded · ${openRows} rejected row${openRows === 1 ? "" : "s"} still open`}
          </div>
        </div>
      </button>

      {open && (
        <div className="space-y-2 border-t border-navy-100 px-3 py-2.5">
          {run.error_code && <div className="font-mono text-[10px] text-subtle">{run.error_code}</div>}
          {run.reject_total > run.reject_stored && (
            <div className="text-[11px] text-amber-700">
              {run.reject_total} rows were rejected; the first {run.reject_stored} are kept here.
              Download or re-ingest the file to handle the rest.
            </div>
          )}
          {rejects.length > 0 && (
            <div className="max-h-56 overflow-auto rounded-md border border-navy-100">
              <table className="w-full text-left text-[10.5px]">
                <thead className="sticky top-0 bg-navy-50 text-subtle">
                  <tr><th className="px-2 py-1">Line</th><th className="px-2 py-1">Reason</th>
                      <th className="px-2 py-1">Row</th><th className="px-2 py-1">State</th></tr>
                </thead>
                <tbody>
                  {rejects.map((r) => (
                    <tr key={r.reject_id} className="border-t border-navy-100 align-top">
                      <td className="px-2 py-1 font-mono">{r.line_no ?? "-"}</td>
                      <td className="px-2 py-1 text-rose-700">{r.reason}</td>
                      <td className="px-2 py-1 font-mono text-navy-700">{preview(r)}</td>
                      <td className="px-2 py-1">{r.state}{r.attempts > 0 ? ` · ${r.attempts}×` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {more && (
                <button type="button" onClick={() => loadRejects(rejects.length).catch((e) => setProblem(msg(e)))}
                        className="focus-ring w-full border-t border-navy-100 py-1 text-[11px] text-steel-600 hover:bg-navy-50">
                  Load more
                </button>
              )}
            </div>
          )}

          {!resolved && (
            <div className="flex flex-wrap items-center gap-2">
              {!fileLevel && openRows > 0 && (
                <>
                  <select value={policy} onChange={(e) => setPolicy(e.target.value as RerunPolicy)}
                          aria-label="When a value still does not fit"
                          className="focus-ring rounded-lg border border-navy-100 bg-white px-1.5 py-1 text-[11px]">
                    <option value="reject">Skip rows that still don't fit</option>
                    <option value="truncate">Cut values to fit</option>
                  </select>
                  <Action onClick={rerunRows} busy={busy === "rows"} disabled={!!busy} primary>
                    <RotateCcw size={11} /> Re-run rejected rows
                  </Action>
                </>
              )}
              {fileLevel && run.file_kept && (
                <Action onClick={rerunFile} busy={busy === "file"} disabled={!!busy} primary>
                  <RotateCcw size={11} /> Re-run file
                </Action>
              )}
              {fileLevel && !run.file_kept && (
                <span className="text-[11px] text-subtle">The file was not kept — upload it again.</span>
              )}
              {run.reject_stored > 0 && (
                <Action onClick={download} busy={busy === "download"} disabled={!!busy}>
                  <Download size={11} /> Download rejected rows
                </Action>
              )}
            </div>
          )}
          {!fileLevel && !resolved && openRows > 0 && (
            <div className="text-[10.5px] text-subtle">
              Over-length rows: widen the column in the table first, then re-run.
            </div>
          )}
          {notice && <div className="text-[11px] text-emerald-700">{notice}</div>}
          {problem && <div className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">{problem}</div>}
        </div>
      )}
    </li>
  );
}

function Action(
  { onClick, busy, disabled, primary, children }:
  { onClick: () => void; busy: boolean; disabled: boolean; primary?: boolean; children: React.ReactNode },
) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
            className={cn(
              "focus-ring inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-medium disabled:opacity-50",
              primary ? "bg-navy-800 font-semibold text-white hover:bg-navy-700"
                      : "border border-navy-100 bg-white text-navy-700 hover:bg-navy-50",
            )}>
      {busy ? <Loader2 size={11} className="animate-spin" /> : null}
      {children}
    </button>
  );
}

function preview(r: CsvReject): string {
  const row = r.row;
  if (!row) return "";
  const text = row.columns
    ? Object.entries(row.columns).map(([k, v]) => `${k}=${String(v ?? "")}`).join(", ")
    : (row.cells ?? []).join(" | ");
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

function msg(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}
