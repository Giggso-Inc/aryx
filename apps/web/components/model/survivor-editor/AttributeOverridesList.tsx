const STRATEGIES = [
  "first_non_empty",
  "source_priority",
  "most_recent",
  "most_complete",
  "most_frequent",
] as const;

export function AttributeOverridesList({
  typeName,
  attributes,
  overrides,
  defaultStrategy,
  onChange,
}: {
  typeName: string;
  attributes: string[];
  overrides: Record<string, string> | undefined;
  defaultStrategy: string;
  onChange: (attr: string, value: string) => void;
}) {
  return (
    <div className="rounded-lg border border-navy-100 bg-white">
      <div className="border-b border-navy-100 px-3 py-2">
        <label className="block text-[10px] uppercase tracking-wider text-subtle">
          Per-attribute override · {typeName}
        </label>
      </div>
      {attributes.length === 0 ? (
        <p className="px-3 py-3 text-[11px] italic text-subtle">
          no attributes yet
        </p>
      ) : (
        <ul className="divide-y divide-navy-100/60">
          {attributes.map((a) => (
            <li key={a} className="flex items-center justify-between gap-2 px-3 py-2">
              <span className="truncate font-mono text-[11px] text-navy-700">
                {a}
              </span>
              <select
                value={overrides?.[a] || defaultStrategy}
                onChange={(e) => onChange(a, e.target.value)}
                className="focus-ring rounded-md border border-navy-100 bg-white px-2 py-0.5 font-mono text-[11px] text-navy-800 focus:border-steel-500"
              >
                {STRATEGIES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
