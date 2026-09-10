import { Building2, CreditCard, Users2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type AdminTab = "users" | "subscription" | "company-profile";
export type TableTab = "users" | "invitations";

export const USER_ROLE_OPTIONS = [
  { value: "all", label: "All Roles" },
  { value: "admin", label: "Admin" },
  { value: "manager", label: "Manager" },
  { value: "user", label: "User" },
];

export const USER_STATUS_OPTIONS = [
  { value: "all", label: "All Status" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

export const INVITATION_STATUS_OPTIONS = [
  { value: "all", label: "All Status" },
  { value: "pending", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "expired", label: "Expired" },
];

export const SETTINGS_TABS: Array<{
  id: AdminTab;
  label: string;
  icon: LucideIcon;
}> = [
  { id: "users", label: "Users", icon: Users2 },
  { id: "subscription", label: "Subscription", icon: CreditCard },
  { id: "company-profile", label: "Company Profile", icon: Building2 },
];
