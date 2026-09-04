"use client";

const DEFAULT_FORMATS = ["turtle", "json-ld", "xml", "n-triples"];

export function OntologyFormatPicker({
  availableFormats,
  selectedFormats,
  onToggle,
}: {
  availableFormats: string[];
  selectedFormats: string[];
  onToggle: (fmt: string) => void;
}) {
  const formats = availableFormats.length === 0 ? DEFAULT_FORMATS : availableFormats;
  return (
    <div className="mb-5">
      <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-navy-600">
        Enabled formats
      </div>
      <div className="flex flex-wrap gap-2">
        {formats.map((f) => (
          <label key={f} className="flex cursor-pointer items-center gap-2 rounded-lg border border-navy-100 px-3 py-1.5 hover:bg-navy-50">
            <input
              type="checkbox"
              checked={selectedFormats.includes(f)}
              onChange={() => onToggle(f)}
              className="accent-steel-500"
            />
            <span className="text-[12px] text-navy-800">{f}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
