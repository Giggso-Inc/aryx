-- Table:      attrsequence
-- Source CSV: attrSequence.csv
-- Driven by:  BML scripts 18722390164 (filter by CPQModel + AttrName IN, ORDER BY Seq),
--             18722390561 (CPQModel + BaseModel), 18722390457 (CPQModel + AttrName IN + BaseModel IN)
-- Column naming rule: CSV header cell lowercased, every run of non [a-z0-9] chars
--   replaced by underscore, leading/trailing underscores stripped, and the suffix _col
--   appended if the result is an Oracle reserved word.
-- Types from CSV meta row: String -> VARCHAR2(4000), except the indexed columns (cpqmodel, basemodel,
--   attrname, seq) which are VARCHAR2(1000) so composite indexes stay under the ORA-01450 key-size limit
--   (observed max value length in the sample CSV is 194). All columns NULLable, no constraints.
CREATE TABLE IF NOT EXISTS attrsequence (
    update_action VARCHAR2(4000),
    key VARCHAR2(4000),
    cpqmodel VARCHAR2(1000),
    basemodel VARCHAR2(1000),
    attr1 VARCHAR2(4000),
    val1 VARCHAR2(4000),
    attrname VARCHAR2(1000),
    seq VARCHAR2(1000),
    optionorreqflag VARCHAR2(4000),
    startdate VARCHAR2(4000),
    enddate VARCHAR2(4000),
    createddate VARCHAR2(4000),
    createdby VARCHAR2(4000),
    updateddate VARCHAR2(4000),
    updatedby VARCHAR2(4000)
);
