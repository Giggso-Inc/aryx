import {
  Activity, BookOpen, Database, FileText,
  Home, MessageSquareText, Settings, Share2, Upload,
} from "lucide-react";
import type { WorkspaceSection } from "@/lib/workspace-route";

export function workspaceTabIcon(section: WorkspaceSection) {
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

export function headerMeta(pathname?: string | null) {
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
