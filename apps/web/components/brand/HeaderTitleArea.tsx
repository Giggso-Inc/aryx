"use client";

import { formatWorkspaceName } from "@/lib/workspace-name";
import { WORKSPACE_TABS, workspaceSectionHref, type WorkspaceSection } from "@/lib/workspace-route";
import { TopNavLink } from "./HeaderNavLinks";
import { workspaceTabIcon } from "./header-meta";

export function HeaderTitleArea({
  hasSession,
  shayWorkspaceId,
  workspaceName,
  pathname,
  section,
  workspaceTitle,
  topbarMeta,
}: {
  hasSession: boolean;
  shayWorkspaceId?: string | null;
  workspaceName: string | null;
  pathname?: string | null;
  section?: WorkspaceSection | null;
  workspaceTitle: string | null;
  topbarMeta: { title: string; description?: string };
}) {
  if (hasSession && shayWorkspaceId) {
    return (
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
    );
  }

  if (hasSession) {
    return (
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
    );
  }

  return null;
}
