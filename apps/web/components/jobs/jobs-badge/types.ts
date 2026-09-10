import { api } from "@/lib/api";

export const POLL_MS = 5_000;

export type JobRow = Awaited<ReturnType<typeof api.listJobs>>[number];

export const RUNNING = new Set(["queued", "running", "pending", "in_progress"]);
