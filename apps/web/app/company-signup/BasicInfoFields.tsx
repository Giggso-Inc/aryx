import { Building2, Globe, Mail, User } from "lucide-react";
import { Field } from "./Field";

interface FormErrors {
  companyName?: string;
  domain?: string;
  contactEmail?: string;
  userName?: string;
}

export function BasicInfoFields({
  companyName,
  domain,
  userName,
  contactEmail,
  errors,
  onCompanyNameChange,
  onDomainChange,
  onUserNameChange,
  onContactEmailChange,
}: {
  companyName: string;
  domain: string;
  userName: string;
  contactEmail: string;
  errors: FormErrors;
  onCompanyNameChange: (value: string) => void;
  onDomainChange: (value: string) => void;
  onUserNameChange: (value: string) => void;
  onContactEmailChange: (value: string) => void;
}) {
  return (
    <>
      <Field
        label="Company Name"
        required
        error={errors.companyName}
        icon={<Building2 size={18} />}
      >
        <input
          value={companyName}
          onChange={(event) => onCompanyNameChange(event.target.value)}
          placeholder="Acme Corporation"
          className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
        />
      </Field>

      <Field
        label="Domain"
        required
        error={errors.domain}
        icon={<Globe size={18} />}
      >
        <input
          value={domain}
          onChange={(event) => onDomainChange(event.target.value)}
          placeholder="acme.com"
          className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
        />
      </Field>

      <Field
        label="Contact Email"
        required
        error={errors.contactEmail}
        icon={<Mail size={18} />}
      >
        <input
          type="email"
          value={contactEmail}
          onChange={(event) => onContactEmailChange(event.target.value)}
          placeholder="john@acme.com"
          className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
        />
      </Field>

      <Field
        label="Full Name"
        required
        error={errors.userName}
        icon={<User size={18} />}
      >
        <input
          value={userName}
          onChange={(event) => onUserNameChange(event.target.value)}
          placeholder="John Doe"
          className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
        />
      </Field>
    </>
  );
}
