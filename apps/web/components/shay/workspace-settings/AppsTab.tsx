import { Users2 } from "lucide-react";

export function AppsTab() {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-navy-200 bg-[radial-gradient(circle_at_top_left,_rgba(50,113,214,0.08),_transparent_42%),linear-gradient(180deg,_#ffffff,_#f7f9fd)] px-6 py-12 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-navy-900 text-white">
        <Users2 size={22} />
      </div>
      <h3 className="mt-5 text-2xl font-semibold text-navy-900">Apps are coming soon</h3>
      <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-subtle">
        Workspace app connections will land here next. This tab is reserved for install state,
        permissions, and app-specific workspace controls.
      </p>
    </div>
  );
}
