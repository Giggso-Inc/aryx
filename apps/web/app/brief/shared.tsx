export function FieldGroup({
  label, name, value, onChange, rows = 1,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.1em] text-navy-600">
        {label}
      </label>
      {rows === 1 ? (
        <input
          name={name}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
        />
      ) : (
        <textarea
          name={name}
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="focus-ring w-full resize-none rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
        />
      )}
    </div>
  );
}

export function Readiness({ filled }: { filled: number }) {
  const labels = ["Generic NER", "Grounded", "Grounded", "Sharp", "Expert", "Expert"];
  const pct = Math.round((filled / 5) * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] font-medium text-navy-600">Brief depth</span>
        <span className="text-[11px] font-semibold text-navy-800">{labels[filled]}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-navy-100">
        <div
          className="h-full rounded-full bg-steel-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
