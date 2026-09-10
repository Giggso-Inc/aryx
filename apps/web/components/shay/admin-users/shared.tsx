import type { ReactNode } from "react";

export function RoleBadge({ role }: { role: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700">
      {capitalize(role)}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  body,
}: {
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="col-span-full flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-navy-50 text-navy-700">
        {icon}
      </div>
      <h3 className="mt-4 text-base font-semibold text-navy-900">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-subtle">{body}</p>
    </div>
  );
}

export function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
