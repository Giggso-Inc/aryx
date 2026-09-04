export function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
      <div className="text-[2rem] font-bold text-navy-900">{value}</div>
      <div className="mt-1 text-[12px] text-subtle">{label}</div>
    </div>
  );
}
