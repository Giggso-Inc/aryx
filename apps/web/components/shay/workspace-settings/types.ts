import type { ShayWorkspaceMember } from "@/lib/shay-types";

export type SettingsTab = "members" | "apps" | "danger-zone";

export const MEMBER_ROLES = [
  { value: "admin", label: "Admin" },
  { value: "member", label: "Member" },
  { value: "viewer", label: "Viewer" },
] as const;

export const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: "members", label: "Members" },
  { id: "apps", label: "Apps" },
  { id: "danger-zone", label: "Danger Zone" },
];

export type DisplayWorkspaceMember = ShayWorkspaceMember & {
  derived?: boolean;
  derivedLabel?: string;
};

export function roleLabel(role: string) {
  return MEMBER_ROLES.find((option) => option.value === role)?.label ?? role;
}
