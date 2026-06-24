"use client";
import { useCallback, useState } from "react";
import { AlertCircle, Check, CheckCircle2, Loader2, Zap } from "lucide-react";
import { useWorkspace } from "@/lib/workspace";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useJobPoller } from "./useJobPoller";
import { DbConnectForm } from "./DbConnectForm";
import { DbReviewTables } from "./DbReviewTables";
import type { DbPhase, DiscoveredTable } from "./types";

export function DatabaseTab() {
  const { workspaceId } = useWorkspace();
  const [phase, setPhase] = useState<DbPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [dialect, setDialect] = useState("postgresql");
  const [host, setHost] = useState(""); const [port, setPort] = useState("");
  const [database, setDatabase] = useState(""); const [user, setUser] = useState("");
  const [password, setPassword] = useState(""); const [fullUrl, setFullUrl] = useState("");
  const [useUrl, setUseUrl] = useState(false);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [tables, setTables] = useState<string[]>([]);
  const [context, setContext] = useState("");
  const [discovered, setDiscovered] = useState<DiscoveredTable[]>([]);
  const [edges, setEdges] = useState<Array<{ source_type: string; target_type: string; name: string }>>([]);
  const [ingestJobId, setIngestJobId] = useState<string | null>(null);

  const onIngestDone = useCallback((ok: boolean) => {
    if (!ok) { setPhase("error"); setError("Ingest job failed"); return; }
    setPhase("done");
  }, []);
  useJobPoller(phase === "ingesting" ? ingestJobId : null, onIngestDone);

  const connect = async () => {
    setPhase("connecting"); setError(null);
    try {
      const cfg = useUrl ? { url: fullUrl } : { dialect, host, port, database, user, password };
      const res = await api.dbConnect(cfg);
      setConnectionId(res.connection_id); setTables(res.tables); setPhase("connected");
    } catch (e) { setError(e instanceof Error ? e.message : "Connection failed"); setPhase("error"); }
  };

  const discover = async () => {
    if (!connectionId) return;
    setPhase("discovering"); setError(null);
    try {
      const res = await api.dbDiscover(connectionId, context || "Auto-discover entity types from database tables");
      setDiscovered(res.tables.map((t) => ({ ...t, included: true }))); setEdges(res.edges ?? []); setPhase("review");
    } catch (e) { setError(e instanceof Error ? e.message : "Discovery failed"); setPhase("error"); }
  };

  const ingest = async () => {
    const chosen = discovered.filter((t) => t.included).map((t) => ({ table: t.table, ontology_type: t.ontology_type, match_keys: t.match_keys }));
    if (!chosen.length || !connectionId) return;
    setPhase("ingesting"); setError(null);
    try {
      const res = await api.dbIngestMulti(connectionId, chosen, edges, workspaceId);
      setIngestJobId(res.job_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Ingest failed"); setPhase("error"); }
  };

  const reset = () => {
    setPhase("idle"); setError(null);
    setConnectionId(null); setTables([]); setDiscovered([]); setEdges([]); setIngestJobId(null);
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

  const atConnect = phase === "idle" || phase === "connecting";
  const pastConnect = !atConnect && phase !== "error";
  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
          <button type="button" onClick={reset} className="ml-auto underline">Reset</button>
        </div>
      )}
      <div className={cn("rounded-xl border bg-white p-5 shadow-soft", pastConnect ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
        <div className="mb-4 flex items-center gap-2">
          <span className={cn("flex size-6 items-center justify-center rounded-full text-[11px] font-bold", pastConnect ? "bg-emerald-500 text-white" : "bg-navy-800 text-white")}>
            {pastConnect ? <Check size={12} /> : "1"}
          </span>
          <h3 className="font-semibold text-navy-900">Connect to database</h3>
        </div>
        <DbConnectForm useUrl={useUrl} setUseUrl={setUseUrl} fullUrl={fullUrl} setFullUrl={setFullUrl}
          dialect={dialect} setDialect={setDialect} host={host} setHost={setHost}
          port={port} setPort={setPort} database={database} setDatabase={setDatabase}
          user={user} setUser={setUser} password={password} setPassword={setPassword}
          connecting={phase === "connecting"} onConnect={connect} />
      </div>
      {(phase === "connected" || phase === "discovering" || phase === "review" || phase === "ingesting") && (
        <div className={cn("rounded-xl border bg-white p-5 shadow-soft animate-fade-in",
          phase === "discovering" ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
          <div className="mb-4 flex items-center gap-2">
            <span className={cn("flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
              phase === "review" || phase === "ingesting" ? "bg-emerald-500 text-white" : "bg-navy-800 text-white")}>
              {phase === "review" || phase === "ingesting" ? <Check size={12} /> : "2"}
            </span>
            <h3 className="font-semibold text-navy-900">Auto-discover entity types</h3>
            <span className="ml-auto text-[11px] text-subtle">{tables.length} table{tables.length !== 1 ? "s" : ""} found</span>
          </div>
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Business context (helps agent identify entity types)</label>
            <input value={context} onChange={(e) => setContext(e.target.value)}
              placeholder="e.g. Customer success tables for a SaaS platform"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500" />
          </div>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {tables.map((t) => <span key={t} className="rounded-full bg-navy-50 px-2.5 py-0.5 text-[11px] font-medium text-navy-700">{t}</span>)}
          </div>
          <button type="button" onClick={discover} disabled={phase === "discovering"}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50">
            {phase === "discovering" ? <><Loader2 size={13} className="animate-spin" /> Discovering…</> : <><Zap size={13} /> Run discovery agent</>}
          </button>
        </div>
      )}
      {(phase === "review" || phase === "ingesting") && discovered.length > 0 && (
        <DbReviewTables discovered={discovered} setDiscovered={setDiscovered} edges={edges}
          ingesting={phase === "ingesting"} onIngest={ingest} />
      )}
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
