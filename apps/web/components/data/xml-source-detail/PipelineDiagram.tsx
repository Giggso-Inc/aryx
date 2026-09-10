import { FileCode2 } from "lucide-react";

export function PipelineDiagram() {
  return (
    <section className="rounded-[1.5rem] border border-navy-100 bg-[#EEF4FF] p-5 shadow-soft">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
        Active Transformation Pipe
      </p>
      <div className="mt-5 flex flex-col gap-6 lg:flex-row lg:items-center">
        <div className="flex min-w-[124px] flex-col items-center text-center">
          <div className="flex size-16 items-center justify-center rounded-2xl bg-navy-800 text-white shadow-soft">
            <FileCode2 size={24} />
          </div>
          <span className="mt-3 text-sm font-semibold text-navy-900">XML Root</span>
        </div>
        <div className="flex flex-1 items-center gap-4">
          <div className="h-px flex-1 bg-navy-100" />
          <div className="rounded-full bg-[#6FE2D0] px-5 py-2 text-center text-xs font-semibold uppercase tracking-[0.16em] text-[#045E58] shadow-sm">
            Splitting &amp; Fragmenting
          </div>
          <div className="h-px flex-1 bg-navy-100" />
        </div>
        <div className="flex min-w-[124px] flex-col items-center text-center">
          <div className="grid size-16 grid-cols-2 gap-1 rounded-2xl bg-white p-3 shadow-soft">
            <div className="rounded bg-[#79F1DC]" />
            <div className="rounded bg-[#7C3AED]" />
            <div className="rounded bg-[#FFD7D1]" />
            <div className="rounded bg-[#D5E3FF]" />
          </div>
          <span className="mt-3 text-sm font-semibold text-navy-900">CSV Output</span>
        </div>
      </div>
    </section>
  );
}
