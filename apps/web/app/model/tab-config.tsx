import type { ReactNode } from "react";
import { FolderDown, FolderUp, GitBranch, Scale, Table2, Weight } from "lucide-react";

export type Tab = "lightweight" | "diagram" | "rules" | "versions" | "publish" | "import";

export const TABS: Array<{
  id: Tab;
  label: string;
  icon: ReactNode;
  iconClass: string;
  activeClass: string;
}> = [
  {
    id: "lightweight",
    label: "Lightweight",
    icon: <Weight size={14} strokeWidth={2.25} />,
    iconClass: "text-steel-600",
    activeClass: "border-steel-500 text-steel-700",
  },
  {
    id: "diagram",
    label: "Schema Diagram",
    icon: <Table2 size={14} strokeWidth={2.1} />,
    iconClass: "text-steel-600",
    activeClass: "border-steel-500 text-steel-700",
  },
  {
    id: "rules",
    label: "Rules",
    icon: <Scale size={14} strokeWidth={2.1} />,
    iconClass: "text-purple-600",
    activeClass: "border-purple-500 text-purple-700",
  },
  {
    id: "versions",
    label: "Versions",
    icon: <GitBranch size={14} strokeWidth={2.1} />,
    iconClass: "text-purple-600",
    activeClass: "border-purple-500 text-purple-700",
  },
  {
    id: "publish",
    label: "Publish",
    icon: <FolderUp size={14} strokeWidth={2.1} />,
    iconClass: "text-emerald-600",
    activeClass: "border-emerald-500 text-emerald-700",
  },
  {
    id: "import",
    label: "Import",
    icon: <FolderDown size={14} strokeWidth={2.1} />,
    iconClass: "text-emerald-600",
    activeClass: "border-emerald-500 text-emerald-700",
  },
];
