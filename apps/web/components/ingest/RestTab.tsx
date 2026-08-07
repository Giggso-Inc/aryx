"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Globe, PlayCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import { ComingSoonBadge } from "./DatabaseTab";

/** UI-only shell — no REST ingestion backend exists yet (explicit product
 *  scope decision). The form renders and validates client-side, but
 *  "Preview" is permanently disabled and badged "Coming soon". */
export function RestTab() {
  const [url, setUrl] = useState("");
  const [authName, setAuthName] = useState("Authorization");
  const [authValue, setAuthValue] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [recordPath, setRecordPath] = useState("");
  const [paginationParam, setPaginationParam] = useState("");
  const [maxPages, setMaxPages] = useState("");
  const [entityType, setEntityType] = useState("");

  return (
    <div className="flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <div className="flex items-center gap-2.5">
          <Globe size={20} className="text-steel-600" />
          <h2 className="text-[15px] font-semibold text-navy-900">
            Connect a REST endpoint
          </h2>
          <ComingSoonBadge />
        </div>
        <p className="mt-1 text-[13px] text-subtle">
          Pull records from an API and map them into your knowledge graph.
          This connector is not available yet — the form below is a preview
          of what&apos;s coming.
        </p>

        <div className="mt-4 rounded-2xl border border-navy-100 bg-white p-5">
          <Field label="Endpoint URL">
            <input value={url} onChange={(e) => setUrl(e.target.value)}
                   placeholder="https://api.example.com/v1/records" className={inputCls} />
          </Field>

          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label="Auth header name">
              <input value={authName} onChange={(e) => setAuthName(e.target.value)}
                     placeholder="Authorization" className={inputCls} />
            </Field>
            <Field label="Auth header value">
              <input type="password" value={authValue}
                     onChange={(e) => setAuthValue(e.target.value)}
                     placeholder="Bearer ••••••••" className={inputCls} />
            </Field>
          </div>

          <button
            type="button"
            onClick={() => setAdvancedOpen((v) => !v)}
            className="focus-ring mt-4 flex items-center gap-1.5 text-[12px] font-medium text-navy-700 hover:text-navy-900"
          >
            {advancedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Advanced options
          </button>

          {advancedOpen && (
            <div className={cn("mt-3 grid grid-cols-2 gap-3 rounded-lg border",
                                "border-navy-100 bg-navy-50/40 p-3")}>
              <Field label="Record path">
                <input value={recordPath} onChange={(e) => setRecordPath(e.target.value)}
                       placeholder="data.items" className={inputCls} />
              </Field>
              <Field label="Pagination param">
                <input value={paginationParam} onChange={(e) => setPaginationParam(e.target.value)}
                       placeholder="page" className={inputCls} />
              </Field>
              <Field label="Max pages">
                <input value={maxPages} onChange={(e) => setMaxPages(e.target.value)}
                       placeholder="10" className={inputCls} />
              </Field>
              <Field label="Entity type override">
                <input value={entityType} onChange={(e) => setEntityType(e.target.value)}
                       placeholder="Customer" className={inputCls} />
              </Field>
            </div>
          )}

          <div className="mt-5 flex justify-end">
            <span title="REST ingestion is coming soon" className="inline-block">
              <button
                type="button"
                disabled
                className="focus-ring inline-flex cursor-not-allowed items-center gap-2 rounded-xl bg-navy-800 px-5 py-2.5 text-[14px] font-semibold text-white opacity-50"
              >
                <PlayCircle size={14} /> Preview
              </button>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

const inputCls = "focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500";

function Field({
  label, children,
}: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-subtle">
        {label}
      </span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}
