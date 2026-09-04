"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { ArrowLeft, Menu } from "lucide-react";
import { Logo } from "./Logo";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { HITLBadge } from "@/components/hitl/HITLBadge";
import { JobsBadge } from "@/components/jobs/JobsBadge";
import { parseWorkspaceScope } from "@/lib/workspace-route";
import { AppSidebar } from "./AppSidebar";
import { HeaderTitleArea } from "./HeaderTitleArea";
import { headerMeta } from "./header-meta";

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

            <HeaderTitleArea
              hasSession={hasSession}
              shayWorkspaceId={shayWorkspaceId}
              workspaceName={workspaceName}
              pathname={pathname}
              section={section}
              workspaceTitle={workspaceTitle}
              topbarMeta={topbarMeta}
            />
          </div>

          <div className="flex shrink-0 items-center gap-2 self-start lg:self-auto">
            {hasSession ? (
              <>
                {shayWorkspaceId ? <JobsBadge /> : null}
                {shayWorkspaceId ? <HITLBadge /> : null}
              </>
            ) : null}
          </div>
        </div>
      </header>
    </>
  );
}
