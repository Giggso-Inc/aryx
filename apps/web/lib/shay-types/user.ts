export interface ShayUser {
  id: string;
  name: string;
  email_id: string;
  avatar_url?: string | null;
  company_id: string;
  role: string;
  is_active: boolean;
  last_login?: string | null;
  created_datetime: string;
  updated_datetime: string;
}

export interface ShayUserList {
  users: ShayUser[];
  total: number;
  total_active: number;
  total_inactive: number;
  total_admin: number;
  page: number;
  size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface ShayInvitationInvitedBy {
  userId: string;
  userEmail?: string | null;
  username?: string | null;
  avatar_url?: string | null;
  role?: string | null;
}

export interface ShayInvitation {
  id: string;
  email: string;
  role: string;
  company_id: string;
  invited_by: ShayInvitationInvitedBy;
  status: string;
  message?: string | null;
  created_at: string;
  expires_at: string;
}

export interface ShayInvitationList {
  invitations: ShayInvitation[];
  total: number;
  page: number;
  size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}
