-- Table: attrtopdnonfrequency
-- Source CSV: attrToPDNonFrequency.csv (BML data table, SL3500e_config.xml)
-- Driven by BML queries: ConfigRuleAction_18722390457 and ConfigRuleAction_18722390614 (filter on cpqModel)
-- Column naming rule: header lowercased, runs of non [a-z0-9] replaced by underscore, edge underscores stripped, Oracle reserved words get suffix _col
-- Types from CSV meta row 3: String -> VARCHAR2(4000), except indexed cpqmodel which is VARCHAR2(1000)
--   (keeps index keys well under the ORA-01450 limit). All columns nullable, no constraints.
CREATE TABLE IF NOT EXISTS attrtopdnonfrequency (
    update_action VARCHAR2(4000),
    cpqmodel VARCHAR2(1000),
    attr1 VARCHAR2(4000),
    pdname VARCHAR2(4000),
    invokeutil VARCHAR2(4000),
    iscommattr VARCHAR2(4000)
);
