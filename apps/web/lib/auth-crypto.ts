const SECRET_KEY =
  "9a2b7c4d1e5f80316789a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abc";
const RESET_TOKEN_MAX_AGE_MS = 60 * 60 * 1000;

function hexToArrayBuffer(hex: string): ArrayBuffer {
  const bytes = new Uint8Array(hex.length / 2);
  for (let index = 0; index < hex.length; index += 2) {
    bytes[index / 2] = Number.parseInt(hex.slice(index, index + 2), 16);
  }
  return bytes.buffer;
}

function decodeBase64(value: string) {
  return Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
}

async function decrypt(cipherText: string) {
  const combined = decodeBase64(cipherText);
  const iv = combined.slice(0, 12);
  const encrypted = combined.slice(12, -16);
  const tag = combined.slice(-16);

  const key = await crypto.subtle.importKey(
    "raw",
    hexToArrayBuffer(SECRET_KEY),
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );

  const encryptedWithTag = new Uint8Array(encrypted.length + tag.length);
  encryptedWithTag.set(encrypted, 0);
  encryptedWithTag.set(tag, encrypted.length);

  const decrypted = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv,
    },
    key,
    encryptedWithTag,
  );

  return new TextDecoder().decode(decrypted);
}

function normalizeUrlSafeToken(token: string) {
  const normalized = token.replace(/-/g, "+").replace(/_/g, "/");
  const padding = "=".repeat((4 - (normalized.length % 4)) % 4);
  return normalized + padding;
}

export async function encryptPassword(password: string) {
  const key = await crypto.subtle.importKey(
    "raw",
    hexToArrayBuffer(SECRET_KEY),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
    },
    key,
    new TextEncoder().encode(password),
  );

  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(encrypted), iv.length);
  return btoa(String.fromCharCode(...combined));
}

export async function decodeResetToken(token: string) {
  const candidateValues = [decodeURIComponent(token), token];
  for (const candidate of candidateValues) {
    try {
      const decrypted = await decrypt(candidate);
      const parts = decrypted.split("$@$");
      if (parts.length !== 3) {
        continue;
      }
      const [userId, email, timestamp] = parts;
      const createdAt = Number.parseInt(timestamp, 10) * 1000;
      if (!Number.isFinite(createdAt)) {
        continue;
      }
      const expired = Date.now() - createdAt > RESET_TOKEN_MAX_AGE_MS;
      return {
        user_id: userId.trim(),
        email: email.trim(),
        expiry: createdAt,
        expired,
        valid: true,
      };
    } catch {
      // Try the next candidate format.
    }
  }

  return {
    user_id: "",
    email: "",
    expiry: 0,
    expired: true,
    valid: false,
  };
}

export async function decodeVerificationToken(token: string) {
  const candidateValues = [
    normalizeUrlSafeToken(decodeURIComponent(token)),
    normalizeUrlSafeToken(token),
    decodeURIComponent(token),
    token,
  ];

  for (const candidate of candidateValues) {
    try {
      const decrypted = await decrypt(candidate);
      if (decrypted.trim()) {
        return {
          token: decrypted.trim(),
          valid: true,
        };
      }
    } catch {
      // Try the next candidate format.
    }
  }

  return {
    token: "",
    valid: false,
  };
}
