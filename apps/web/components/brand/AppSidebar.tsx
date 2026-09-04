"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  LayoutGrid, LogOut, Settings, Shield, UserCircle2, X,
} from "lucide-react";
import { Logo } from "./Logo";
import { cn } from "@/lib/cn";
import { SidebarLink } from "./HeaderNavLinks";

export function AppSidebar({
  collapsed,
  mobileOpen,
  pathname,
  displayName,
  showAdminHub,
  onCloseMobile,
  onSignOut,
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  pathname?: string | null;
  displayName?: string;
  showAdminHub: boolean;
  onCloseMobile: () => void;
  onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const avatarText = useMemo(() => {
    const firstToken = (displayName || "Profile").trim().split(/\s+/)[0] || "P";
    return firstToken.charAt(0).toUpperCase();
  }, [displayName]);

  useEffect(() => {
    if (!open) return undefined;

    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-50 bg-navy-950/35 transition-opacity lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onCloseMobile}
      />

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex flex-col border-r border-navy-100 bg-white/96 backdrop-blur transition-all duration-200",
          collapsed ? "w-24" : "w-[204px]",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div className="flex items-center justify-between border-b border-navy-100 px-4 py-4">
          <Link href="/workspaces" className="focus-ring rounded-2xl" onClick={onCloseMobile}>
            <Logo size={38} withWordmark={!collapsed} showTagline={false} />
          </Link>
          <button
            type="button"
            onClick={onCloseMobile}
            className="focus-ring inline-flex items-center justify-center rounded-xl border border-navy-100 bg-white p-2 text-navy-700 hover:bg-navy-50 lg:hidden"
            aria-label="Close sidebar"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 px-3 py-5">
          <div className="space-y-2">
            <SidebarLink
              href="/workspaces"
              icon={<LayoutGrid size={18} />}
              label="Workspaces"
              active={pathname === "/workspaces" || pathname?.startsWith("/workspaces/") || false}
              collapsed={collapsed}
              onClick={onCloseMobile}
            />
            {showAdminHub ? (
              <SidebarLink
                href="/admin"
                icon={<Shield size={18} />}
                label="Admin Hub"
                active={pathname?.startsWith("/admin") || false}
                collapsed={collapsed}
                onClick={onCloseMobile}
              />
            ) : null}
            <SidebarLink
              href="/settings"
              icon={<Settings size={18} />}
              label="Settings"
              active={pathname === "/settings" || pathname?.startsWith("/settings/") || false}
              collapsed={collapsed}
              onClick={onCloseMobile}
            />
          </div>
          <div className="mt-5 border-t border-navy-100" />
        </div>

        <div className="border-t border-navy-100 px-3 py-4">
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              className={cn(
                "focus-ring flex w-full items-center rounded-2xl border border-navy-100 bg-canvas px-3 py-3 text-left text-sm text-navy-700 hover:bg-navy-50",
                collapsed ? "justify-center" : "gap-3",
              )}
              aria-haspopup="menu"
              aria-expanded={open}
              aria-label="Open profile menu"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-navy-800 text-[12px] font-semibold text-white">
                {avatarText}
              </span>
              {!collapsed ? (
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-navy-900">
                    {displayName || "Signed in"}
                  </span>
                  <span className="block text-xs text-subtle">Profile menu</span>
                </span>
              ) : null}
            </button>

            {open && (
              <div
                className={cn(
                  "absolute bottom-16 z-[70] min-w-52 overflow-hidden rounded-2xl border border-navy-100 bg-white shadow-soft",
                  collapsed ? "left-0" : "left-0 right-0",
                )}
              >
                <div className="border-b border-navy-100 px-4 py-3">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
                    Profile
                  </div>
                  <div className="mt-1 text-sm font-medium text-navy-900">
                    {displayName || "Signed in"}
                  </div>
                </div>
                <Link
                  href="/profile"
                  className="focus-ring flex items-center gap-2 px-4 py-3 text-sm font-medium text-navy-700 hover:bg-navy-50"
                  onClick={() => {
                    setOpen(false);
                    onCloseMobile();
                  }}
                >
                  <UserCircle2 size={14} />
                  Profile page
                </Link>
                <button
                  type="button"
                  onClick={onSignOut}
                  className="focus-ring flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-navy-700 hover:bg-navy-50"
                  role="menuitem"
                >
                  <LogOut size={14} />
                  Log out
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
