"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import {
  Activity, ArrowLeft, BookOpen, Database, FileText,
  Home, LayoutGrid, LogOut, Menu, MessageSquareText, Settings, Share2, Shield,
  Upload, UserCircle2, X,
} from "lucide-react";
import { Logo } from "./Logo";
import { cn } from "@/lib/cn";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { formatWorkspaceName } from "@/lib/workspace-name";
import { HITLBadge } from "@/components/hitl/HITLBadge";
import { JobsBadge } from "@/components/jobs/JobsBadge";
import {
  parseWorkspaceScope,
  WORKSPACE_TABS,
  type WorkspaceSection,
  workspaceSectionHref,
} from "@/lib/workspace-route";

interface HeaderProps {
  workspaceId?: number;
  onWorkspaceChange?: (id: number) => void;
}

const SIDEBAR_STATE_KEY = "aryx.sidebar.collapsed";
const EXPANDED_OFFSET = "204px";
const COLLAPSED_OFFSET = "96px";

export function Header({ workspaceId, onWorkspaceChange }: HeaderProps) {
  void workspaceId;
  void onWorkspaceChange;
  const { session, profile, clearSession } = useShayAuth();
  const router = useRouter();
  const hasSession = !!session;
  const canAccessAdminHub = (profile?.role ?? session?.role) === "admin";
  const pathname = usePathname();
  const { shayWorkspaceId, section } = parseWorkspaceScope(pathname);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.localStorage.getItem(SIDEBAR_STATE_KEY) === "true";
  });
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [workspaceName, setWorkspaceName] = useState<string | null>(null);
  const topbarMeta = headerMeta(pathname);

  useEffect(() => {
    if (!shayWorkspaceId || !session?.access_token) {
      setWorkspaceName(null);
      return;
    }

    let active = true;
    shayApi.getWorkspace(shayWorkspaceId, session.access_token)
      .then((workspace) => {
        if (active) {
          setWorkspaceName(workspace.name);
        }
      })
      .catch(() => {
        if (active) {
          setWorkspaceName(null);
        }
      });

    return () => {
      active = false;
    };
  }, [session?.access_token, shayWorkspaceId]);

  const workspaceTitle = pathname === "/settings" ? "Settings" : null;

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const syncOffset = () => {
      const nextOffset = !hasSession
        ? "0px"
        : window.innerWidth < 1024
          ? "0px"
          : sidebarCollapsed
            ? COLLAPSED_OFFSET
            : EXPANDED_OFFSET;
      document.documentElement.style.setProperty("--app-shell-offset", nextOffset);
    };

    syncOffset();
    window.addEventListener("resize", syncOffset);
    return () => {
      window.removeEventListener("resize", syncOffset);
      document.documentElement.style.setProperty("--app-shell-offset", "0px");
    };
  }, [hasSession, sidebarCollapsed]);

  const toggleSidebar = () => {
    const nextValue = !sidebarCollapsed;
    setSidebarCollapsed(nextValue);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_STATE_KEY, String(nextValue));
    }
  };

  return (
    <>
      {hasSession ? (
        <AppSidebar
          collapsed={sidebarCollapsed}
          mobileOpen={mobileSidebarOpen}
          pathname={pathname}
          displayName={profile?.name || session?.name || session?.email_id}
          showAdminHub={canAccessAdminHub}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onSignOut={() => {
            clearSession();
            router.replace("/login");
          }}
        />
      ) : null}

      <header
        data-app-shell={hasSession ? "sidebar" : "public"}
        className="sticky top-0 z-40 border-b border-navy-100/90 bg-canvas/95 backdrop-blur supports-[backdrop-filter]:bg-canvas/88"
      >
        <div className="mx-auto grid max-w-[1600px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 px-4 py-3 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            {hasSession && shayWorkspaceId ? (
              <div className="flex shrink-0">
                <Link
                  href="/workspaces"
                  className="focus-ring inline-flex h-11 w-11 items-center justify-center rounded-full text-navy-700 hover:bg-navy-50"
                  aria-label="Back to workspaces"
                >
                  <ArrowLeft size={20} />
                </Link>
              </div>
            ) : hasSession ? (
              <div className="flex shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    if (typeof window !== "undefined" && window.innerWidth < 1024) {
                      setMobileSidebarOpen(true);
                      return;
                    }
                    toggleSidebar();
                  }}
                  className="focus-ring inline-flex h-11 w-11 items-center justify-center rounded-full text-navy-700 hover:bg-navy-50"
                  aria-label="Toggle sidebar"
                >
                  <Menu size={22} />
                </button>
              </div>
            ) : (
              <Link href="/" className="focus-ring rounded-md">
                <Logo size={34} withWordmark showTagline={false} />
              </Link>
            )}

            {hasSession && shayWorkspaceId ? (
              <div className="flex min-w-0 flex-1 items-center gap-4">
                <div className="min-w-0 max-w-[clamp(11rem,24vw,23rem)]">
                  <h1 className="truncate text-base font-semibold text-navy-900 md:text-[1.05rem]">
                    {workspaceName ? formatWorkspaceName(workspaceName) : "Workspace"}
                  </h1>
                </div>
                <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                  {WORKSPACE_TABS.map((tab) => {
                    const href = workspaceSectionHref(shayWorkspaceId, tab.section);
                    const active = pathname === href
                      || pathname?.startsWith(`${href}/`)
                      || (tab.section === "ask" && pathname?.includes(`/workspaces/${shayWorkspaceId}/chats/`))
                      || tab.section === section;
                    return (
                      <TopNavLink
                        key={href}
                        href={href}
                        label={tab.label}
                        icon={workspaceTabIcon(tab.section)}
                        active={!!active}
                      />
                    );
                  })}
                </nav>
              </div>
            ) : hasSession ? (
              <div>
                <h1 className="text-base font-semibold text-navy-900 md:text-lg">
                  {workspaceTitle || topbarMeta.title}
                </h1>
                {topbarMeta.description ? (
                  <p className="mt-0.5 text-xs text-subtle md:text-[13px]">
                    {topbarMeta.description}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex shrink-0 items-center gap-2 self-start lg:self-auto">
            {hasSession ? (
              <>
                {shayWorkspaceId ? <JobsBadge /> : null}
                {shayWorkspaceId ? <HITLBadge /> : null}
              </>
            ) : (
              <Link
                href="/login"
                className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 px-3 py-1.5 text-[13px] font-medium text-navy-700 hover:bg-navy-50"
              >
                Login
              </Link>
            )}
          </div>
        </div>
      </header>
    </>
  );
}

function AppSidebar({
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

function SidebarLink({
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

function TopNavLink({
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

function workspaceTabIcon(section: WorkspaceSection) {
  switch (section) {
    case "home":
      return <Home size={15} />;
    case "brief":
      return <FileText size={15} />;
    case "ingest":
      return <Upload size={15} />;
    case "data":
      return <Database size={15} />;
    case "graph":
      return <Share2 size={15} />;
    case "ontology":
      return <BookOpen size={15} />;
    case "ask":
      return <MessageSquareText size={15} />;
    case "observability":
      return <Activity size={15} />;
    case "settings":
      return <Settings size={15} />;
    default:
      return null;
  }
}

function headerMeta(pathname?: string | null) {
  if (!pathname || pathname === "/") {
    return {
      title: "Ask",
      description: "Ask questions about your data and activity.",
    };
  }
  if (pathname.startsWith("/workspaces")) {
    return {
      title: "Workspaces",
      description: "Create, browse, and manage company workspaces.",
    };
  }
  if (pathname.startsWith("/admin")) {
    return {
      title: "Admin Hub",
      description: "Manage company users, roles, and workspace access.",
    };
  }
  if (pathname.startsWith("/profile")) {
    return {
      title: "Profile",
      description: "Review your account details and company context.",
    };
  }
  if (pathname === "/settings") {
    return {
      title: "Settings",
      description: "Manage platform-wide tokens, ontology options, and guarded reset controls.",
    };
  }
  return {
    title: "Aryx",
    description: "Navigate your workspace and connected tools.",
  };
}
