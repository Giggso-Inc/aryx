"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle, Check, CheckCircle2, ChevronDown, ChevronRight,
  Database, FileText, Globe, Loader2, Plus, Trash2, Upload, Zap,
} from "lucide-react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import type { DiscoverySummary } from "@/lib/types";

type Tab = "database" | "docs" | "rest";

// ── Shared job progress poller ────────────────────────────────────────────────

function useJobPoller(jobId: string | null, onDone: (ok: boolean) => void) {
  const [stage, setStage] = useState<string | null>(null);
  const [pct, setPct] = useState<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let dead = false;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (dead) return;
        setStage(j.stage);
        setPct(j.pct);
        if (j.status === "complete") { onDone(true); return; }
        if (j.status === "failed") { onDone(false); return; }
      } catch { /* ignore transient */ }
      if (!dead) setTimeout(tick, 1500);
    };
    tick();
    return () => { dead = true; };
  }, [jobId, onDone]);

  return { stage, pct };
}

// ── Database Tab ─────────────────────────────────────────────────────────────

const DIALECTS = ["postgresql", "mysql", "mariadb", "oracle", "sqlite"] as const;

type DbPhase = "idle" | "connecting" | "connected" | "discovering" | "review" | "ingesting" | "done" | "error";

interface DiscoveredTable {
  table: string;
  ontology_type: string;
  match_keys: string[];
  included: boolean;
}

function DatabaseTab() {
  const { workspaceId } = useWorkspace();

  const [phase, setPhase] = useState<DbPhase>("idle");
  const [error, setError] = useState<string | null>(null);

  // connection form
  const [dialect, setDialect] = useState<string>("postgresql");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [database, setDatabase] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [fullUrl, setFullUrl] = useState("");
  const [useUrl, setUseUrl] = useState(false);

  // post-connect
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [tables, setTables] = useState<string[]>([]);

  // discover
  const [context, setContext] = useState("");
  const [discovered, setDiscovered] = useState<DiscoveredTable[]>([]);
  const [edges, setEdges] = useState<Array<{ source_type: string; target_type: string; name: string }>>([]);

  // ingest job
  const [ingestJobId, setIngestJobId] = useState<string | null>(null);
  const onIngestDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Ingest job failed"); return; }
    setPhase("done");
  }, []);
  useJobPoller(phase === "ingesting" ? ingestJobId : null, onIngestDone);

  const connect = async () => {
    setPhase("connecting"); setError(null);
    try {
      const cfg = useUrl
        ? { url: fullUrl }
        : { dialect, host, port, database, user, password };
      const res = await api.dbConnect(cfg);
      setConnectionId(res.connection_id);
      setTables(res.tables);
      setPhase("connected");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
      setPhase("error");
    }
  };

  const discover = async () => {
    if (!connectionId) return;
    setPhase("discovering"); setError(null);
    try {
      const res = await api.dbDiscover(connectionId, context || "Auto-discover entity types from database tables");
      setDiscovered(res.tables.map((t) => ({ ...t, included: true })));
      setEdges(res.edges ?? []);
      setPhase("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discovery failed");
      setPhase("error");
    }
  };

  const ingest = async () => {
    const chosen = discovered.filter((t) => t.included).map((t) => ({
      table: t.table,
      ontology_type: t.ontology_type,
      match_keys: t.match_keys,
    }));
    if (!chosen.length || !connectionId) return;
    setPhase("ingesting"); setError(null);
    try {
      const res = await api.dbIngestMulti(connectionId, chosen, edges, workspaceId);
      setIngestJobId(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest failed");
      setPhase("error");
    }
  };

  const reset = () => {
    setPhase("idle"); setError(null);
    setConnectionId(null); setTables([]); setDiscovered([]); setEdges([]);
    setIngestJobId(null);
  };

  if (phase === "done") return (
    <div className="py-12 text-center animate-fade-in">
      <CheckCircle2 size={40} className="mx-auto mb-3 text-emerald-500" />
      <h3 className="text-lg font-semibold text-navy-900">Database ingest complete</h3>
      <p className="mt-1 text-[13px] text-subtle">Tables have been ingested into your knowledge graph.</p>
      <button type="button" onClick={reset}
        className="focus-ring mt-5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50">
        Ingest more tables
      </button>
    </div>
  );

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
          <button type="button" onClick={reset} className="ml-auto underline">Reset</button>
        </div>
      )}

      {/* Step 1: Connect */}
      <div className={cn("rounded-xl border bg-white p-5 shadow-soft",
        phase !== "idle" && phase !== "connecting" ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
        <div className="mb-4 flex items-center gap-2">
          <span className={cn(
            "flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
            phase !== "idle" && phase !== "connecting" ? "bg-emerald-500 text-white" : "bg-navy-800 text-white",
          )}>
            {phase !== "idle" && phase !== "connecting" ? <Check size={12} /> : "1"}
          </span>
          <h3 className="font-semibold text-navy-900">Connect to database</h3>
        </div>

        <label className="mb-3 flex cursor-pointer items-center gap-2 text-[12px] text-navy-600">
          <input type="checkbox" checked={useUrl} onChange={(e) => setUseUrl(e.target.checked)} className="accent-steel-500" />
          Use connection URL instead
        </label>

        {useUrl ? (
          <div className="mb-4">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Connection URL</label>
            <input
              value={fullUrl}
              onChange={(e) => setFullUrl(e.target.value)}
              placeholder="postgresql://user:pass@host:5432/dbname"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
            />
          </div>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">RDBMS</label>
                <select
                  value={dialect}
                  onChange={(e) => setDialect(e.target.value)}
                  className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
                >
                  {DIALECTS.map((d) => <option key={d}>{d}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Host</label>
                <input
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="db.example.com"
                  className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Port</label>
                <input
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder="5432"
                  className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
            </div>
            <div className="mb-3">
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Database</label>
              <input
                value={database}
                onChange={(e) => setDatabase(e.target.value)}
                placeholder="sales"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
              />
            </div>
            <div className="mb-4 grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">User</label>
                <input
                  value={user}
                  onChange={(e) => setUser(e.target.value)}
                  className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
            </div>
          </>
        )}

        <button
          type="button"
          onClick={connect}
          disabled={phase === "connecting" || (!useUrl && !host && !database) || (useUrl && !fullUrl)}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {phase === "connecting"
            ? <><Loader2 size={13} className="animate-spin" /> Connecting…</>
            : <><Database size={13} /> Connect &amp; introspect</>}
        </button>
      </div>

      {/* Connected: show tables + context */}
      {(phase === "connected" || phase === "discovering" || phase === "review" || phase === "ingesting") && (
        <div className={cn("rounded-xl border bg-white p-5 shadow-soft animate-fade-in",
          phase === "discovering" ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
          <div className="mb-4 flex items-center gap-2">
            <span className={cn(
              "flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
              phase === "review" || phase === "ingesting" ? "bg-emerald-500 text-white" : "bg-navy-800 text-white",
            )}>
              {phase === "review" || phase === "ingesting" ? <Check size={12} /> : "2"}
            </span>
            <h3 className="font-semibold text-navy-900">Auto-discover entity types</h3>
            <span className="ml-auto text-[11px] text-subtle">{tables.length} table{tables.length !== 1 ? "s" : ""} found</span>
          </div>

          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">
              Business context (helps agent identify entity types)
            </label>
            <input
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder="e.g. Customer success tables for a SaaS platform"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
            />
          </div>

          <div className="mb-4 flex flex-wrap gap-1.5">
            {tables.map((t) => (
              <span key={t} className="rounded-full bg-navy-50 px-2.5 py-0.5 text-[11px] font-medium text-navy-700">
                {t}
              </span>
            ))}
          </div>

          <button
            type="button"
            onClick={discover}
            disabled={phase === "discovering"}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {phase === "discovering"
              ? <><Loader2 size={13} className="animate-spin" /> Discovering…</>
              : <><Zap size={13} /> Run discovery agent</>}
          </button>
        </div>
      )}

      {/* Review proposed tables */}
      {(phase === "review" || phase === "ingesting") && discovered.length > 0 && (
        <div className={cn("rounded-xl border bg-white p-5 shadow-soft animate-fade-in",
          phase === "ingesting" ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
          <div className="mb-4 flex items-center gap-2">
            <span className={cn(
              "flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
              phase === "ingesting" ? "bg-emerald-500 text-white" : "bg-navy-800 text-white",
            )}>
              {phase === "ingesting" ? <Check size={12} /> : "3"}
            </span>
            <h3 className="font-semibold text-navy-900">Review &amp; confirm</h3>
            <span className="ml-auto text-[11px] text-subtle">
              {discovered.filter((d) => d.included).length} of {discovered.length} selected
            </span>
          </div>

          <div className="mb-4 space-y-2">
            {discovered.map((t, i) => (
              <div
                key={t.table}
                className={cn(
                  "rounded-lg border p-3 transition-colors",
                  t.included ? "border-steel-200 bg-steel-50" : "border-navy-100 bg-white opacity-60",
                )}
              >
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={t.included}
                    onChange={() => setDiscovered((prev) =>
                      prev.map((d, j) => j === i ? { ...d, included: !d.included } : d)
                    )}
                    className="mt-1 accent-steel-500"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="font-medium text-[12px] text-navy-900">{t.table}</span>
                      <span className="text-[10px] text-subtle">→</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="mb-0.5 block text-[10px] text-navy-500">Entity type</label>
                        <input
                          value={t.ontology_type}
                          onChange={(e) => setDiscovered((prev) =>
                            prev.map((d, j) => j === i ? { ...d, ontology_type: e.target.value } : d)
                          )}
                          className="focus-ring w-full rounded border border-navy-100 bg-white px-2 py-1 text-[12px] focus:border-steel-500"
                        />
                      </div>
                      <div>
                        <label className="mb-0.5 block text-[10px] text-navy-500">Match keys (comma-sep)</label>
                        <input
                          value={t.match_keys.join(",")}
                          onChange={(e) => setDiscovered((prev) =>
                            prev.map((d, j) => j === i ? {
                              ...d,
                              match_keys: e.target.value.split(",").map((k) => k.trim()).filter(Boolean),
                            } : d)
                          )}
                          className="focus-ring w-full rounded border border-navy-100 bg-white px-2 py-1 text-[12px] focus:border-steel-500"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {edges.length > 0 && (
            <div className="mb-4 rounded-lg border border-navy-100 bg-navy-50/40 px-3 py-2 text-[11px] text-navy-600">
              <strong>Relationships found:</strong>{" "}
              {edges.slice(0, 5).map((e) => `${e.source_type}→${e.target_type} (${e.name})`).join(", ")}
              {edges.length > 5 && ` +${edges.length - 5} more`}
            </div>
          )}

          <button
            type="button"
            onClick={ingest}
            disabled={discovered.filter((d) => d.included).length === 0}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            <CheckCircle2 size={13} /> Ingest selected tables
          </button>
        </div>
      )}

      {/* Ingest progress */}
      {phase === "ingesting" && (
        <div className="flex items-center gap-3 rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <Loader2 size={18} className="animate-spin text-steel-500" />
          <div>
            <p className="font-medium text-navy-900">Ingesting tables to graph…</p>
            <p className="text-[12px] text-subtle">This may take a few minutes for large tables.</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Document Discovery Tab ────────────────────────────────────────────────────

type DocPhase = "idle" | "reading" | "summary" | "confirming" | "done" | "error";

function DocsTab() {
  const { workspaceId } = useWorkspace();
  const [files, setFiles] = useState<File[]>([]);
  const [context, setContext] = useState("");
  const [phase, setPhase] = useState<DocPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [readJobId, setReadJobId] = useState<string | null>(null);
  const [discoveryId, setDiscoveryId] = useState<string | null>(null);
  const [summary, setSummary] = useState<DiscoverySummary | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [confirmJobId, setConfirmJobId] = useState<string | null>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  const onReadDone = useCallback(async (ok: boolean) => {
    if (!ok || !discoveryId) { setPhase("error"); setError("Read job failed"); return; }
    try {
      const s = await api.getDiscoverySummary(discoveryId);
      setSummary(s);
      setApproved(new Set((s.types || []).map((t) => t.type)));
      // Tabular files are always included — user can see them but can't deselect yet.
      setPhase("summary");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Summary fetch failed");
      setPhase("error");
    }
  }, [discoveryId]);

  const onConfirmDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Confirm job failed"); return; }
    setPhase("done");
  }, []);

  const readPoller = useJobPoller(phase === "reading" ? readJobId : null, onReadDone);
  const confirmPoller = useJobPoller(phase === "confirming" ? confirmJobId : null, onConfirmDone);

  const start = async () => {
    if (!files.length) return;
    setPhase("reading"); setError(null);
    try {
      const r = await api.readDocs(workspaceId, files, context);
      setDiscoveryId(r.discovery_id);
      setReadJobId(r.discovery_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setPhase("error");
    }
  };

  const confirm = async () => {
    if (!discoveryId) return;
    // Always include all tabular files the read step found.
    const approvedFiles = (summary?.files ?? []).map((f) => f.filename);
    if (approved.size === 0 && approvedFiles.length === 0) return;
    setPhase("confirming"); setError(null);
    try {
      const r = await api.confirmDiscovery(discoveryId, [...approved], approvedFiles);
      setConfirmJobId(r.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirm failed");
      setPhase("error");
    }
  };

  const reset = () => {
    setFiles([]); setContext(""); setPhase("idle"); setError(null);
    setReadJobId(null); setDiscoveryId(null); setSummary(null);
    setApproved(new Set()); setConfirmJobId(null);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = [...e.dataTransfer.files];
    setFiles((prev) => [...prev, ...dropped]);
  };

  const toggleType = (type: string) => {
    setApproved((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  };

  if (phase === "done") return (
    <div className="py-12 text-center animate-fade-in">
      <CheckCircle2 size={40} className="mx-auto mb-3 text-emerald-500" />
      <h3 className="text-lg font-semibold text-navy-900">Ingest complete</h3>
      <p className="mt-1 text-[13px] text-subtle">Entities are now in your knowledge graph.</p>
      <button
        type="button"
        onClick={reset}
        className="focus-ring mt-5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50"
      >
        Ingest more documents
      </button>
    </div>
  );

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
          <button type="button" onClick={reset} className="ml-auto underline">Reset</button>
        </div>
      )}

      {/* Step 1: Upload */}
      <div className={cn("rounded-xl border bg-white p-5 shadow-soft",
        phase === "idle" ? "border-navy-100" : "border-navy-50 opacity-60 pointer-events-none")}>
        <div className="mb-3 flex items-center gap-2">
          <span className={cn(
            "flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
            phase !== "idle" ? "bg-emerald-500 text-white" : "bg-navy-800 text-white",
          )}>
            {phase !== "idle" ? <Check size={12} /> : "1"}
          </span>
          <h3 className="font-semibold text-navy-900">Upload files</h3>
        </div>

        <div
          ref={dropRef}
          onDrop={onDrop}
          onDragOver={(e) => e.preventDefault()}
          className="mb-3 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-navy-200 bg-navy-50/40 py-8 hover:bg-navy-50"
          onClick={() => document.getElementById("doc-file-input")?.click()}
        >
          <Upload size={24} className="mb-2 text-navy-400" />
          <p className="text-[13px] text-navy-600">Drop files here or click to browse</p>
          <p className="mt-0.5 text-[11px] text-subtle">DOCX, PDF, PPTX, RTF, HTML, CSV, JSON</p>
          <input
            id="doc-file-input"
            type="file"
            multiple
            accept=".docx,.pdf,.pptx,.rtf,.html,.csv,.json,.xml"
            className="hidden"
            onChange={(e) => e.target.files && setFiles((p) => [...p, ...Array.from(e.target.files!)])}
          />
        </div>

        {files.length > 0 && (
          <ul className="mb-3 space-y-1">
            {files.map((f, i) => (
              <li key={i} className="flex items-center gap-2 rounded-lg bg-navy-50 px-3 py-1.5 text-[12px]">
                <FileText size={12} className="text-steel-500" />
                <span className="flex-1 truncate text-navy-700">{f.name}</span>
                <span className="text-subtle">{(f.size / 1024).toFixed(0)} KB</span>
                <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="text-subtle hover:text-rose-500">×</button>
              </li>
            ))}
          </ul>
        )}

        <div className="mb-3">
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Business context (optional)</label>
          <input
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="e.g. Customer success documents for a SaaS company"
            className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
          />
        </div>

        <button
          type="button"
          onClick={start}
          disabled={!files.length || phase !== "idle"}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          <Zap size={13} /> Read &amp; discover types
        </button>
      </div>

      {/* Step 2: Reading progress */}
      {(phase === "reading") && (
        <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-navy-800 text-[11px] font-bold text-white">2</span>
            <h3 className="font-semibold text-navy-900">Reading &amp; discovering entities…</h3>
            <Loader2 size={14} className="animate-spin text-steel-500 ml-auto" />
          </div>
          {readPoller.pct != null && (
            <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-navy-100">
              <div
                className="h-full rounded-full bg-steel-500 transition-all duration-500"
                style={{ width: `${readPoller.pct}%` }}
              />
            </div>
          )}
          <p className="text-[12px] text-subtle">{readPoller.stage || "Processing…"}</p>
        </div>
      )}

      {/* Step 3: Summary + approval */}
      {(phase === "summary" || phase === "confirming") && summary && (
        <div className={cn("rounded-xl border bg-white p-5 shadow-soft animate-fade-in",
          phase === "confirming" ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
          <div className="mb-4 flex items-center gap-2">
            <span className={cn(
              "flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
              phase === "confirming" ? "bg-emerald-500 text-white" : "bg-navy-800 text-white",
            )}>
              {phase === "confirming" ? <Check size={12} /> : "2"}
            </span>
            <h3 className="font-semibold text-navy-900">Review discovered types</h3>
            <span className="ml-auto text-[11px] text-subtle">{approved.size} of {summary.types.length} selected</span>
          </div>
          <div className="space-y-2 mb-4">
            {summary.types.map((t) => (
              <div
                key={t.type}
                onClick={() => toggleType(t.type)}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors",
                  approved.has(t.type)
                    ? "border-steel-200 bg-steel-50"
                    : "border-navy-100 bg-white hover:bg-navy-50",
                )}
              >
                <div className={cn(
                  "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border",
                  approved.has(t.type)
                    ? "border-steel-500 bg-steel-500"
                    : "border-navy-300",
                )}>
                  {approved.has(t.type) && <Check size={10} className="text-white" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-navy-900">{t.type}</span>
                    <span className="rounded-full bg-navy-100 px-2 py-0.5 text-[10px] font-medium text-navy-600">
                      {t.count} mention{t.count !== 1 ? "s" : ""}
                    </span>
                  </div>
                  {t.examples.filter(Boolean).length > 0 && (
                    <p className="mt-0.5 truncate text-[11px] text-subtle">
                      e.g. {t.examples.filter(Boolean).slice(0, 3).join(", ")}
                    </p>
                  )}
                </div>
              </div>
            ))}
            {summary.types.length === 0 && (summary.files ?? []).length === 0 && (
              <p className="py-2 text-[12px] text-subtle italic">
                No entity types found. Try uploading a document with named entities (PDF, DOCX) or a CSV/JSON file.
              </p>
            )}
            {/* Tabular files — shown read-only; all are included in the ingest */}
            {(summary.files ?? []).length > 0 && (
              <div className="mt-1">
                {summary.types.length > 0 && (
                  <p className="mb-1 text-[11px] font-medium text-navy-600">Tabular files (all will be ingested)</p>
                )}
                {summary.files.map((f) => (
                  <div key={f.filename}
                    className="mb-1.5 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                    <FileText size={12} className="shrink-0 text-emerald-600" />
                    <span className="flex-1 truncate text-[12px] font-medium text-navy-800">{f.filename}</span>
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                      {f.ontology_type}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={confirm}
              disabled={approved.size === 0 && (summary.files ?? []).length === 0}
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
            >
              <CheckCircle2 size={13} /> Confirm &amp; ingest
            </button>
            <button type="button" onClick={reset}
              className="focus-ring rounded-lg px-3 py-2 text-[13px] text-navy-600 hover:bg-navy-50">
              Start over
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Confirm progress */}
      {phase === "confirming" && (
        <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-navy-800 text-[11px] font-bold text-white">3</span>
            <h3 className="font-semibold text-navy-900">Ingesting to graph…</h3>
            <Loader2 size={14} className="animate-spin text-steel-500 ml-auto" />
          </div>
          {confirmPoller.pct != null && (
            <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-navy-100">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all duration-500"
                style={{ width: `${confirmPoller.pct}%` }}
              />
            </div>
          )}
          <p className="text-[12px] text-subtle">{confirmPoller.stage || "Writing entities…"}</p>
        </div>
      )}
    </div>
  );
}

// ── REST API Tab ──────────────────────────────────────────────────────────────

type RestPhase = "idle" | "previewing" | "preview" | "ingesting" | "done" | "error";

function RestTab() {
  const { workspaceId } = useWorkspace();
  const [url, setUrl] = useState("");
  const [authHeader, setAuthHeader] = useState("");
  const [authValue, setAuthValue] = useState("");
  const [recordPath, setRecordPath] = useState("");
  const [pageParam, setPageParam] = useState("");
  const [maxPages, setMaxPages] = useState("20");
  const [context, setContext] = useState("");
  const [phase, setPhase] = useState<RestPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<{ sample: unknown[]; count: number; inferred_type: string } | null>(null);
  const [ontologyType, setOntologyType] = useState("");
  const [ingestJobId, setIngestJobId] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const buildHeaders = () => authHeader && authValue ? { [authHeader]: authValue } : {};

  const preview = async () => {
    if (!url.trim()) return;
    setPhase("previewing"); setError(null);
    try {
      const r = await api.previewRestIngest({
        workspace_id: workspaceId,
        url: url.trim(),
        headers: buildHeaders(),
        record_path: recordPath || undefined,
        page_param: pageParam || undefined,
        context: context || undefined,
      });
      setPreviewData(r);
      if (!ontologyType && r.inferred_type) setOntologyType(r.inferred_type);
      setPhase("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed");
      setPhase("error");
    }
  };

  const onIngestDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Ingest job failed"); return; }
    setPhase("done");
  }, []);

  useJobPoller(phase === "ingesting" ? ingestJobId : null, onIngestDone);

  const ingest = async () => {
    setPhase("ingesting"); setError(null);
    try {
      const r = await api.startRestIngest({
        workspace_id: workspaceId,
        url: url.trim(),
        headers: buildHeaders(),
        record_path: recordPath || undefined,
        page_param: pageParam || undefined,
        max_pages: parseInt(maxPages) || 20,
        ontology_type: ontologyType || undefined,
        context: context || undefined,
      });
      setIngestJobId(r.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest failed");
      setPhase("error");
    }
  };

  const reset = () => {
    setUrl(""); setPhase("idle"); setError(null); setPreviewData(null);
    setIngestJobId(null); setOntologyType("");
  };

  if (phase === "done") return (
    <div className="py-12 text-center animate-fade-in">
      <CheckCircle2 size={40} className="mx-auto mb-3 text-emerald-500" />
      <h3 className="text-lg font-semibold text-navy-900">REST API ingest complete</h3>
      <p className="mt-1 text-[13px] text-subtle">Records have been ingested into your knowledge graph.</p>
      <button type="button" onClick={reset}
        className="focus-ring mt-5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50">
        Ingest another endpoint
      </button>
    </div>
  );

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
          <button type="button" onClick={reset} className="ml-auto underline">Reset</button>
        </div>
      )}

      {/* Config form */}
      <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
        <h3 className="mb-4 font-semibold text-navy-900">Endpoint Configuration</h3>

        <div className="mb-3">
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Endpoint URL *</label>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://api.example.com/v1/customers"
            className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
          />
        </div>

        <div className="mb-3 grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header name</label>
            <input
              value={authHeader}
              onChange={(e) => setAuthHeader(e.target.value)}
              placeholder="Authorization"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header value</label>
            <input
              value={authValue}
              onChange={(e) => setAuthValue(e.target.value)}
              type="password"
              placeholder="Bearer token123…"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="focus-ring mb-3 flex items-center gap-1 text-[12px] text-navy-600 hover:text-navy-900"
        >
          {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Advanced options
        </button>

        {showAdvanced && (
          <div className="mb-3 space-y-3 rounded-lg border border-navy-100 bg-navy-50/40 p-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">JSON record path</label>
                <input
                  value={recordPath}
                  onChange={(e) => setRecordPath(e.target.value)}
                  placeholder="data.items"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500"
                />
                <p className="mt-0.5 text-[10px] text-subtle">Dot path to the records array</p>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Pagination param</label>
                <input
                  value={pageParam}
                  onChange={(e) => setPageParam(e.target.value)}
                  placeholder="page"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Max pages</label>
                <input
                  value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value)}
                  type="number"
                  min="1"
                  max="200"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">Entity type override</label>
                <input
                  value={ontologyType}
                  onChange={(e) => setOntologyType(e.target.value)}
                  placeholder="Customer (auto-inferred)"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500"
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Business context</label>
              <input
                value={context}
                onChange={(e) => setContext(e.target.value)}
                placeholder="CRM customer records for SaaS"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500"
              />
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={preview}
          disabled={!url.trim() || phase === "previewing"}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50 disabled:opacity-50"
        >
          {phase === "previewing"
            ? <Loader2 size={13} className="animate-spin" />
            : <Globe size={13} />}
          Preview
        </button>
      </div>

      {/* Preview results */}
      {phase === "preview" && previewData && (
        <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold text-navy-900">Preview</h3>
            <span className="text-[11px] text-subtle">{previewData.count} record{previewData.count !== 1 ? "s" : ""} — type: <strong>{previewData.inferred_type}</strong></span>
          </div>
          <div className="mb-4 max-h-40 overflow-auto rounded-lg border border-navy-100 bg-navy-950 p-3">
            <pre className="text-[11px] text-navy-200">
              {JSON.stringify(previewData.sample.slice(0, 3), null, 2)}
            </pre>
          </div>
          <div className="mb-4">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Entity type for all records</label>
            <input
              value={ontologyType}
              onChange={(e) => setOntologyType(e.target.value)}
              className="focus-ring w-full max-w-xs rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500"
            />
          </div>
          <button
            type="button"
            onClick={ingest}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700"
          >
            <Zap size={13} /> Ingest to graph
          </button>
        </div>
      )}

      {/* Ingesting progress */}
      {phase === "ingesting" && (
        <div className="flex items-center gap-3 rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
          <Loader2 size={18} className="animate-spin text-steel-500" />
          <div>
            <p className="font-medium text-navy-900">Ingesting records…</p>
            <p className="text-[12px] text-subtle">This may take a minute for large datasets.</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function IngestPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("database");

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        <div className="mb-6">
          <h1 className="font-display text-2xl font-bold text-navy-900">Ingest</h1>
          <p className="mt-0.5 text-[13px] text-subtle">
            Add data to your knowledge graph — database, documents or REST APIs
          </p>
        </div>

        {/* Tabs */}
        <div className="mb-6 flex gap-0.5 rounded-xl bg-navy-50 p-1">
          {([
            { id: "database" as Tab, label: "Database",  icon: <Database size={14} /> },
            { id: "docs"     as Tab, label: "Documents", icon: <FileText size={14} /> },
            { id: "rest"     as Tab, label: "REST API",  icon: <Globe size={14} /> },
          ]).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                "focus-ring flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-all",
                tab === t.id
                  ? "bg-white text-navy-900 shadow-soft"
                  : "text-navy-600 hover:text-navy-900",
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {tab === "database" && <DatabaseTab />}
        {tab === "docs" && <DocsTab />}
        {tab === "rest" && <RestTab />}
      </main>
    </div>
  );
}
