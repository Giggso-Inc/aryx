import { useEffect } from "react";
import { shayApi } from "@/lib/shay-api";

export function useInviteLoader({
  encryptedInvite,
  onLoaded,
  onError,
  onDone,
}: {
  encryptedInvite: string;
  onLoaded: (invite: { email_id: string; invite_id: string; company_id: string; role: string }) => void;
  onError: (message: string) => void;
  onDone: () => void;
}) {
  useEffect(() => {
    if (!encryptedInvite) return;
    let cancelled = false;

    const loadInvite = async () => {
      try {
        const invite = await shayApi.decryptRegistrationInvite(encryptedInvite);
        if (cancelled) return;
        onLoaded(invite);
      } catch {
        if (!cancelled) {
          onError("Invalid or expired invitation link.");
        }
      } finally {
        if (!cancelled) {
          onDone();
        }
      }
    };

    void loadInvite();

    return () => {
      cancelled = true;
    };
  }, [encryptedInvite]);
}
