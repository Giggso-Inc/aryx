import { useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { EntityNode } from "./types";

interface PathFinderProps {
  entities: EntityNode[];
  workspaceId: number;
  onPath: (ids: number[]) => void;
}

export function PathFinder({ entities, workspaceId, onPath }: PathFinderProps) {
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const find = async () => {
    if (!from || !to) return;
    setLoading(true); setError(null);
    try {
      const path = await api.getEntityPath(from, to, workspaceId);
      onPath(path.map((e) => e.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No path found");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-end gap-2">
      <div>
        <label className="mb-0.5 block text-[10px] font-medium text-navy-600">From</label>
        <select
          value={from ?? ""}
          onChange={(e) => setFrom(Number(e.target.value) || null)}
          className="focus-ring w-40 rounded-lg border border-navy-100 bg-white px-2 py-1.5 text-[12px]"
        >
          <option value="">Select…</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>{e.name} ({e.type})</option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-0.5 block text-[10px] font-medium text-navy-600">To</label>
        <select
          value={to ?? ""}
          onChange={(e) => setTo(Number(e.target.value) || null)}
          className="focus-ring w-40 rounded-lg border border-navy-100 bg-white px-2 py-1.5 text-[12px]"
        >
          <option value="">Select…</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>{e.name} ({e.type})</option>
          ))}
        </select>
      </div>
      <button
        type="button"
        onClick={find}
        disabled={!from || !to || loading}
        className="focus-ring inline-flex items-center gap-1 rounded-lg bg-steel-500 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-steel-600 disabled:opacity-50"
      >
        {loading ? <Loader2 size={11} className="animate-spin" /> : null}
        Find path
      </button>
      {error && <span className="text-[11px] text-rose-600">{error}</span>}
    </div>
  );
}
