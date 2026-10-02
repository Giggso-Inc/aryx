# attrtopdnonfrequency - BML source reference

- Table: `attrtopdnonfrequency`
- Source CSV: `attrToPDNonFrequency.csv` (columns: `_update_action, cpqModel, attr1, Pdname, invokeUtil, isCommAttr`, all String)
- XML source: `SL3500e_config.xml`

## Column mapping
| CSV header | Column |
|---|---|
| _update_action | update_action |
| cpqModel | cpqmodel |
| attr1 | attr1 |
| Pdname | pdname |
| invokeUtil | invokeutil |
| isCommAttr | iscommattr |

## Matching BML scripts

### Script 18722390457
- guid: `e708e380-5756-4ee1-a590-d754054bed30`
- class: `com.bm.xchange.bmscript.configuration.action.ConfigRuleAction_18722390457`
- BMQL (XML line 52319):
```
SELECT attr1 FROM attrToPDNonFrequency WHERE cpqModel=$cpqModel
```

### Script 18722390614
- guid: `ec6c47f4-f47e-4f6f-a9b6-2f468b395fb0`
- class: `com.bm.xchange.bmscript.configuration.action.ConfigRuleAction_18722390614`
- BMQL (XML line 53046):
```
SELECT cpqModel,attr1,Pdname,invokeUtil FROM attrToPDNonFrequency WHERE cpqModel = $cpqModel
```

## Index rationale
| Query | Index | Why |
|---|---|---|
| 18722390457 | idx_attrtopdnonfrequency_cpqmodel (cpqmodel) | Single equality filter on cpqModel |
| 18722390614 | idx_attrtopdnonfrequency_cpqmodel (cpqmodel) | Same filter; no ORDER BY or range predicate |

A covering index (cpqmodel plus selected columns) is not used because VARCHAR2(4000) columns together exceed the Oracle index key size limit. No other columns are queried, so no further indexes are created.
