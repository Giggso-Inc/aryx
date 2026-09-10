"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";

export function SidebarLink({
  href,
  icon,
  label,
  active,
  collapsed,
  onClick,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
  collapsed: boolean;
  onClick: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "focus-ring flex items-center rounded-2xl px-3 py-3 text-sm font-medium transition-colors",
        collapsed ? "justify-center" : "gap-3",
        active
          ? "bg-navy-800 text-white"
          : "text-navy-600 hover:bg-navy-50 hover:text-navy-900",
      )}
    >
      {icon}
      {!collapsed ? <span>{label}</span> : null}
    </Link>
  );
}

export function TopNavLink({
  href,
  label,
  icon,
  active,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  active: boolean;
}) {
  const router = useRouter();
  const warmRoute = () => {
    router.prefetch(href);
  };

  return (
    <Link
      href={href}
      prefetch
      onMouseEnter={warmRoute}
      onFocus={warmRoute}
      className={cn(
        "focus-ring inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-[13px] font-medium transition-colors",
        active
          ? "bg-navy-800 text-white shadow-sm"
          : "text-navy-600 hover:bg-navy-50 hover:text-navy-900",
      )}
    >
      <span className="shrink-0">{icon}</span>
      {label}
    </Link>
  );
}
