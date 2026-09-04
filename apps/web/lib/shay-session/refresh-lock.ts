const SHAY_REFRESH_LOCK_STORAGE_KEY = "aryx.shay.refresh.lock";
const REFRESH_LOCK_TTL_MS = 15_000;

export interface RefreshLockState {
  owner: string;
  refreshToken: string;
  startedAt: number;
}

export function readRefreshLockState(): RefreshLockState | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(SHAY_REFRESH_LOCK_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<RefreshLockState>;
    if (
      typeof parsed.owner !== "string"
      || typeof parsed.refreshToken !== "string"
      || typeof parsed.startedAt !== "number"
      || !Number.isFinite(parsed.startedAt)
    ) {
      return null;
    }
    return parsed as RefreshLockState;
  } catch {
    return null;
  }
}

export function isRefreshLockActive(lock: RefreshLockState | null, refreshToken?: string | null) {
  if (!lock) {
    return false;
  }
  if (refreshToken && lock.refreshToken !== refreshToken) {
    return false;
  }
  return Date.now() - lock.startedAt < REFRESH_LOCK_TTL_MS;
}

function createRefreshLockOwner() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `refresh-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function tryAcquireRefreshLock(refreshToken: string) {
  if (typeof window === "undefined") {
    return null;
  }
  const activeLock = readRefreshLockState();
  if (isRefreshLockActive(activeLock, refreshToken)) {
    return null;
  }
  const owner = createRefreshLockOwner();
  const nextLock: RefreshLockState = {
    owner,
    refreshToken,
    startedAt: Date.now(),
  };
  window.localStorage.setItem(SHAY_REFRESH_LOCK_STORAGE_KEY, JSON.stringify(nextLock));
  const confirmedLock = readRefreshLockState();
  return confirmedLock?.owner === owner ? owner : null;
}

export function releaseRefreshLock(owner: string) {
  if (typeof window === "undefined") {
    return;
  }
  const activeLock = readRefreshLockState();
  if (activeLock?.owner === owner) {
    window.localStorage.removeItem(SHAY_REFRESH_LOCK_STORAGE_KEY);
  }
}
