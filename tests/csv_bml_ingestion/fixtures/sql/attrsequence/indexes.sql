-- Indexes for attrsequence, chosen from the BML queries in bml_source.md.
-- Every query filters CPQModel by equality, so it leads each index.

-- Script 18722390164: CPQModel = x AND AttrName IN (...) ORDER BY Seq. Its prefix also serves script 18722390457.
CREATE INDEX IF NOT EXISTS idx_attrsequence_cpqmodel_attrname_seq ON attrsequence (cpqmodel, attrname, seq);

-- Script 18722390561: CPQModel = x AND BaseModel = y. Script 18722390457: AttrName IN and BaseModel IN.
CREATE INDEX IF NOT EXISTS idx_attrsequence_cpqmodel_basemodel_attrname ON attrsequence (cpqmodel, basemodel, attrname);
