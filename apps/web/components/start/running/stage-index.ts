/** Map backend stage names to the visual pipeline index. The pipeline
 *  is the user-facing story: read → tag → dedupe → link → map → ready.
 *  Pipeline stages on the backend may be: extract / land / tag / map /
 *  resolve / relate / project / done. */
const STAGE_TO_INDEX: Record<string, number> = {
  extract: 0, read: 0,
  land: 0, landed: 0,
  tag: 1, tagging: 1,
  map: 1, mapping: 1, "map-fields": 1,
  resolve: 2, dedupe: 2, cluster: 2,
  relate: 3, link: 3, "fk-link": 3,
  project: 4,
  done: 5, complete: 5, ready: 5,
};

export function stageIndex(stage: string | null): number {
  if (!stage) return 0;
  const key = stage.toLowerCase().trim();
  if (key in STAGE_TO_INDEX) return STAGE_TO_INDEX[key];
  // Loose match: any stage containing one of the known tokens.
  for (const [k, v] of Object.entries(STAGE_TO_INDEX)) {
    if (key.includes(k)) return v;
  }
  return 0;
}
