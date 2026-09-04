import { Database } from "lucide-react";
import type { ShayDatasource } from "@/lib/shay-types";

export function DataSourcesPanel({ datasources }: { datasources: ShayDatasource[] }) {
  return (
    <section className="space-y-4">
      <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
        <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
          <Database size={15} />
          Recent data sources
        </div>
        <div className="mt-4 space-y-3">
          {datasources.slice(0, 4).map((datasource) => (
            <div key={datasource.id} className="rounded-2xl border border-navy-100 px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-navy-900">{datasource.name}</p>
                  <p className="mt-1 text-xs text-subtle">
                    {datasource.storage_type} · {datasource.provider || "manual"} · {datasource.processing_status}
                  </p>
                </div>
                <span className="rounded-full bg-navy-50 px-2.5 py-1 text-[11px] text-navy-700">
                  {datasource.is_connected ? "Connected" : "Draft"}
                </span>
              </div>
            </div>
          ))}
          {datasources.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-navy-200 px-4 py-6 text-sm text-subtle">
              No workspace data sources yet. Add the first one in workspace settings.
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
