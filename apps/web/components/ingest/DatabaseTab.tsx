"use client";

import { useState } from "react";
import { Database, Link2 } from "lucide-react";
import { cn } from "@/lib/cn";

const DIALECTS = ["PostgreSQL", "MySQL", "SQL Server", "Oracle", "Snowflake", "BigQuery"];

/** UI-only shell — no ingestion backend exists for direct database
 *  connections yet (explicit product scope decision). The form renders and
 *  validates client-side, but "Connect & introspect" is permanently
 *  disabled and badged "Coming soon". */
export function DatabaseTab() {
  const [mode, setMode] = useState<"fields" | "url">("fields");
  const [dialect, setDialect] = useState(DIALECTS[0]);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [database, setDatabase] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [connUrl, setConnUrl] = useState("");

  return (
    <div className="flex flex-col items-center px-6 py-10">
      <div className="w-full max-w-2xl">
        <div className="flex items-center gap-2.5">
          <Database size={20} className="text-steel-600" />
          <h2 className="text-[15px] font-semibold text-navy-900">
            Connect a database
          </h2>
          <ComingSoonBadge />
        </div>
        <p className="mt-1 text-[13px] text-subtle">
          Introspect a live database and map its tables into your knowledge
          graph. This connector is not available yet — the form below is a
          preview of what&apos;s coming.
        </p>

        <div className="mt-5 inline-flex rounded-lg border border-navy-100 bg-white p-0.5">
          <button
            type="button"
            onClick={() => setMode("fields")}
            className={cn(
              "rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors",
              mode === "fields" ? "bg-navy-800 text-white" : "text-navy-600 hover:bg-navy-50",
            )}
          >
            Connection fields
          </button>
          <button
            type="button"
            onClick={() => setMode("url")}
            className={cn(
              "rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors",
              mode === "url" ? "bg-navy-800 text-white" : "text-navy-600 hover:bg-navy-50",
            )}
          >
            Connection URL
          </button>
        </div>

        <div className="mt-4 rounded-2xl border border-navy-100 bg-white p-5">
          {mode === "fields" ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Dialect" className="col-span-2">
                <select
                  value={dialect}
                  onChange={(e) => setDialect(e.target.value)}
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
                >
                  {DIALECTS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </Field>
              <Field label="Host">
                <input value={host} onChange={(e) => setHost(e.target.value)}
                       placeholder="db.example.com" className={inputCls} />
              </Field>
              <Field label="Port">
                <input value={port} onChange={(e) => setPort(e.target.value)}
                       placeholder="5432" className={inputCls} />
              </Field>
              <Field label="Database">
                <input value={database} onChange={(e) => setDatabase(e.target.value)}
                       placeholder="analytics" className={inputCls} />
              </Field>
              <Field label="User">
                <input value={user} onChange={(e) => setUser(e.target.value)}
                       placeholder="readonly_user" className={inputCls} />
              </Field>
              <Field label="Password" className="col-span-2">
                <input type="password" value={password}
                       onChange={(e) => setPassword(e.target.value)}
                       placeholder="••••••••" className={inputCls} />
              </Field>
            </div>
          ) : (
            <Field label="Connection URL">
              <input
                value={connUrl}
                onChange={(e) => setConnUrl(e.target.value)}
                placeholder="postgresql://user:pass@host:5432/database"
                className={inputCls}
              />
            </Field>
          )}

          <div className="mt-5 flex justify-end">
            <span title="Direct database ingestion is coming soon" className="inline-block">
              <button
                type="button"
                disabled
                className="focus-ring inline-flex cursor-not-allowed items-center gap-2 rounded-xl bg-navy-800 px-5 py-2.5 text-[14px] font-semibold text-white opacity-50"
              >
                <Link2 size={14} /> Connect &amp; introspect
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
  label, children, className,
}: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="text-[11px] font-semibold uppercase tracking-wider text-subtle">
        {label}
      </span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

export function ComingSoonBadge() {
  return (
    <span
      title="Not available in this release"
      className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-800"
    >
      Coming soon
    </span>
  );
}
