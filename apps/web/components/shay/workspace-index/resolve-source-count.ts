export function resolveWorkspaceDataSourceCount({
  summarySourceCount,
  catalogSourceCount,
  datasourceTotal,
  datasourceItemsCount,
}: {
  summarySourceCount: number | null;
  catalogSourceCount: number | null;
  datasourceTotal: number | null;
  datasourceItemsCount: number | null;
}) {
  const candidates = [
    summarySourceCount,
    catalogSourceCount,
    datasourceTotal,
    datasourceItemsCount,
  ];
  const firstPositive = candidates.find(
    (value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0,
  );
  if (typeof firstPositive === "number") {
    return firstPositive;
  }
  const firstKnown = candidates.find(
    (value): value is number => typeof value === "number" && Number.isFinite(value),
  );
  return firstKnown ?? null;
}
