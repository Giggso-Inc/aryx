"use client";
import { useState } from "react";
import { ChevronDown, ChevronRight, Globe, Loader2 } from "lucide-react";

const inp = "focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500";
const inpBg = "focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] focus:border-steel-500";

interface Props {
  url: string; setUrl: (v: string) => void;
  authHeader: string; setAuthHeader: (v: string) => void;
  authValue: string; setAuthValue: (v: string) => void;
  recordPath: string; setRecordPath: (v: string) => void;
  pageParam: string; setPageParam: (v: string) => void;
  maxPages: string; setMaxPages: (v: string) => void;
  ontologyType: string; setOntologyType: (v: string) => void;
  context: string; setContext: (v: string) => void;
  previewing: boolean;
  onPreview: () => void;
}

export function RestConfigForm(p: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  return (
    <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
      <h3 className="mb-4 font-semibold text-navy-900">Endpoint Configuration</h3>

      <div className="mb-3">
        <label className="mb-1 block text-[11px] font-medium text-navy-600">Endpoint URL *</label>
        <input value={p.url} onChange={(e) => p.setUrl(e.target.value)}
          placeholder="https://api.example.com/v1/customers" className={inp} />
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header name</label>
          <input value={p.authHeader} onChange={(e) => p.setAuthHeader(e.target.value)}
            placeholder="Authorization" className={inp} />
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-medium text-navy-600">Auth header value</label>
          <input value={p.authValue} onChange={(e) => p.setAuthValue(e.target.value)}
            type="password" placeholder="Bearer token123…" className={inp} />
        </div>
      </div>

      <button type="button" onClick={() => setShowAdvanced((v) => !v)}
        className="focus-ring mb-3 flex items-center gap-1 text-[12px] text-navy-600 hover:text-navy-900">
        {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Advanced options
      </button>

      {showAdvanced && (
        <div className="mb-3 space-y-3 rounded-lg border border-navy-100 bg-navy-50/40 p-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">JSON record path</label>
              <input value={p.recordPath} onChange={(e) => p.setRecordPath(e.target.value)}
                placeholder="data.items" className={inpBg} />
              <p className="mt-0.5 text-[10px] text-subtle">Dot path to the records array</p>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Pagination param</label>
              <input value={p.pageParam} onChange={(e) => p.setPageParam(e.target.value)}
                placeholder="page" className={inpBg} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Max pages</label>
              <input value={p.maxPages} onChange={(e) => p.setMaxPages(e.target.value)}
                type="number" min="1" max="200" className={inpBg} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-navy-600">Entity type override</label>
              <input value={p.ontologyType} onChange={(e) => p.setOntologyType(e.target.value)}
                placeholder="Customer (auto-inferred)" className={inpBg} />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Business context</label>
            <input value={p.context} onChange={(e) => p.setContext(e.target.value)}
              placeholder="CRM customer records for SaaS" className={inpBg} />
          </div>
        </div>
      )}

      <button type="button" onClick={p.onPreview} disabled={!p.url.trim() || p.previewing}
        className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-200 bg-white px-4 py-2 text-[13px] font-medium text-navy-700 hover:bg-navy-50 disabled:opacity-50">
        {p.previewing ? <Loader2 size={13} className="animate-spin" /> : <Globe size={13} />}
        Preview
      </button>
    </div>
  );
}
