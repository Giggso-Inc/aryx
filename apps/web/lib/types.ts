// Wire types — these mirror the FastAPI JSON contract, hand-written for V1.
// Later: regenerate from /openapi.json at build time. They live HERE (in the
// frontend) and never get imported back into Python — backend stays oblivious.

export * from "./types/workspace";
export * from "./types/ask";
export * from "./types/lab";
export * from "./types/data-sources";
export * from "./types/data-source-detail";
export * from "./types/ontology";
export * from "./types/ingest";
export * from "./types/observability";
export * from "./types/mcp";
