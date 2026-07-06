export const PASSWORD_REQUIREMENT_LABELS = [
  "At least 8 characters",
  "At least 1 lowercase letter (a-z)",
  "At least 1 uppercase letter (A-Z)",
  "At least 1 number (0-9)",
  "At least 1 special character (!@#$%^&*)",
] as const;

export const PASSWORD_POLICY_ERROR_MESSAGE =
  "Password must be at least 8 characters and include uppercase, lowercase, number, and special character.";

export function getPasswordRequirementFlags(password: string) {
  return [
    password.length >= 8,
    /[a-z]/.test(password),
    /[A-Z]/.test(password),
    /\d/.test(password),
    /[!@#$%^&*()_+\-=[\]{}|;:,.<>?]/.test(password),
  ] as const;
}

export function isPasswordPolicyValid(password: string) {
  return getPasswordRequirementFlags(password).every(Boolean);
}
