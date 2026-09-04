export function BriefSummary({
  domain,
  aim,
  scope,
  objectives,
  roles,
}: {
  domain: string;
  aim: string;
  scope: string;
  objectives: string;
  roles: string;
}) {
  return (
    <div className="mt-5 rounded-xl border border-navy-100 bg-navy-50/40 p-5">
      <h3 className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-navy-500">
        Current brief
      </h3>
      <dl className="space-y-2 text-[13px]">
        {domain && <div><dt className="inline font-semibold text-navy-700">Domain: </dt><dd className="inline text-navy-600">{domain}</dd></div>}
        {aim && <div><dt className="inline font-semibold text-navy-700">Aim: </dt><dd className="inline text-navy-600">{aim}</dd></div>}
        {scope && <div><dt className="inline font-semibold text-navy-700">Scope: </dt><dd className="inline text-navy-600">{scope}</dd></div>}
        {objectives && <div><dt className="inline font-semibold text-navy-700">Objectives: </dt><dd className="inline text-navy-600">{objectives.split("\n").filter(Boolean).join(" · ")}</dd></div>}
        {roles && <div><dt className="inline font-semibold text-navy-700">Participants: </dt><dd className="inline text-navy-600">{roles.split("\n").filter(Boolean).join(" · ")}</dd></div>}
      </dl>
    </div>
  );
}
