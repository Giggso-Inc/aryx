"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { workspaceSectionHref } from "@/lib/workspace-route";

const tabs = [
  { label: "Home", section: "home" },
  { label: "Settings", section: "settings" },
] as const;

export function ShayWorkspaceTabs({ workspaceId }: { workspaceId: string }) {
  const pathname = usePathname();

  return (
    <div className="flex flex-wrap gap-2">
      {tabs.map((tab) => {
        const href = workspaceSectionHref(workspaceId, tab.section);
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "rounded-full px-4 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-navy-800 text-white"
                : "bg-navy-50 text-navy-700 hover:bg-navy-100",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
