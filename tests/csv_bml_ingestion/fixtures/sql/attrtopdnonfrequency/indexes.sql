-- Indexes for attrtopdnonfrequency
-- Both BML queries filter only on cpqModel with a single equality predicate and have no ORDER BY.
-- A single-column index suffices: one equality predicate, no ORDER BY.
-- Query 18722390457 (SELECT attr1 ... WHERE cpqModel = :v) and query 18722390614 (SELECT cpqModel, attr1, Pdname, invokeUtil ... WHERE cpqModel = :v) share one access path.
CREATE INDEX IF NOT EXISTS idx_attrtopdnonfrequency_cpqmodel ON attrtopdnonfrequency (cpqmodel);
