# attrsequence - BML source reference

- Table: `attrsequence`
- Source CSV: `attrSequence.csv` (header: `_update_action,key,CPQModel,BaseModel,attr1,val1,AttrName,Seq,optionOrReqFlag,startDate,endDate,createdDate,createdBy,updatedDate,updatedBy`; all columns `String`)
- XML source: `SL3500e_config.xml`

## Table name resolution

The scripts reference the table as `$attrSeqTableName`. They first assign the literal
`attrSeqTableName = "attrSequence";` and then optionally override it with
`jsonget(dataTableJson,"ATTR_SEQUENCE")` (falling back to `"attrSequence"` if empty).
By default it resolves to `attrSequence`, i.e. the table `attrsequence` (Oracle identifiers are case-insensitive).

## BML scripts and queries

| Script id | GUID | Java class |
|---|---|---|
| 18722390164 | 02dd20f4-a18c-4e8e-bb84-ed2941b66f79 | com.bm.xchange.bmscript.configuration.action.ConfigRuleAction_18722390164 |
| 18722390561 | d10ec029-cbf2-417e-bfb6-b034c9edfa59 | com.bm.xchange.bmscript.configuration.action.ConfigRuleAction_18722390561 |
| 18722390457 | e708e380-5756-4ee1-a590-d754054bed30 | com.bm.xchange.bmscript.configuration.action.ConfigRuleAction_18722390457 |

Q1 (18722390164):
```
SELECT AttrName,Seq,optionOrReqFlag FROM $attrSeqTableName WHERE CPQModel=$cpqModel AND (AttrName in $filter) AND (val1 IS NULL or (attr1='validationOrg' AND val1=$valOrg)) ORDER BY Seq ASC
```

Q2 (18722390561):
```
SELECT AttrName,Seq ,optionOrReqFlag FROM $attrSeqTableName WHERE CPQModel=$cpqModel and (val1 IS NULL or (attr1='validationOrg' AND val1=$valOrg)) AND BaseModel=$modelSelectionBaseModel2_apcr
```

Q3 (18722390457):
```
SELECT BaseModel FROM $attrSeqTableName WHERE CPQModel=$cpqModel and AttrName in $allPDAttrs and BaseModel in $baseModel
```

## Index rationale

| Query | Index | Access path |
|---|---|---|
| Q1 | `idx_attrsequence_cpqmodel_attrname_seq (cpqmodel, attrname, seq)` | equality on CPQModel, IN on AttrName; Seq trailing to help ORDER BY |
| Q2 | `idx_attrsequence_cpqmodel_basemodel_attrname (cpqmodel, basemodel, attrname)` | equality on CPQModel and BaseModel |
| Q3 | `idx_attrsequence_cpqmodel_basemodel_attrname` | CPQModel, BaseModel IN and AttrName IN all in the index |

The `val1`/`attr1` predicates are residual filters on the matched rows and are not indexed.

Note: the indexed columns (`cpqmodel`, `basemodel`, `attrname`, `seq`) are declared `VARCHAR2(1000)` rather than 4000 so the composite indexes stay under Oracle's index-key size limit (ORA-01450).
