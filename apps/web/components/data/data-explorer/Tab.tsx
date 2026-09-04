export function Tab({ icon, label, active, onClick }: {
  icon: React.ReactNode; label: string; active: boolean; onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick}
      className={"flex items-center gap-1.5 border-b-2 px-4 py-2 text-[13px] font-semibold " +
        (active ? "border-steel-500 text-navy-900"
                : "border-transparent text-subtle hover:text-navy-700")}>
      {icon} {label}
    </button>
  );
}
