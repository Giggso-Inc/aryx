# Attribution — src/aryx/cpq_ingestion/raw_graph/xml_projector.py

Last updated: 2026-10-04T06:50:10.216512+00:00
Total lines: 254
Lines AI-generated: 89 (35.0%)
Lines human-typed: 51
Lines joint: 0
Lines unattributed: 114
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-10 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.039066+00:00 | pre-commit gap — unattributed by the local hook |
| 11-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679088+00:00 | pre-commit gap — unattributed by the local hook |
| 13-17 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:47:33.017976+00:00 |  |
| 18-18 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679157+00:00 | pre-commit gap — unattributed by the local hook |
| 19-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:53:53.791207+00:00 | pre-commit gap — unattributed by the local hook |
| 21-23 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T06:41:41.971365+00:00 |  |
| 24-31 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 32-39 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.581953+00:00 | pre-commit gap — unattributed by the local hook |
| 40-40 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:33:36.713738+00:00 |  |
| 41-43 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T06:18:55.438746+00:00 |  |
| 44-44 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.039581+00:00 | pre-commit gap — unattributed by the local hook |
| 45-46 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:33:36.713738+00:00 |  |
| 47-47 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.040278+00:00 | pre-commit gap — unattributed by the local hook |
| 48-94 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T08:44:58.784176+00:00 |  |
| 95-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.581995+00:00 | pre-commit gap — unattributed by the local hook |
| 96-96 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 97-113 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T06:19:10.961395+00:00 |  |
| 114-131 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 132-133 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.582079+00:00 | pre-commit gap — unattributed by the local hook |
| 134-134 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 135-137 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.582121+00:00 | pre-commit gap — unattributed by the local hook |
| 138-150 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 151-151 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.582164+00:00 | pre-commit gap — unattributed by the local hook |
| 152-156 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679222+00:00 | pre-commit gap — unattributed by the local hook |
| 157-159 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T09:28:32.088494+00:00 |  |
| 160-160 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679315+00:00 | pre-commit gap — unattributed by the local hook |
| 161-163 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 164-164 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:50:10.004078+00:00 | pre-commit gap — unattributed by the local hook |
| 165-165 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 166-166 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:50:10.004171+00:00 | pre-commit gap — unattributed by the local hook |
| 167-167 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679379+00:00 | pre-commit gap — unattributed by the local hook |
| 168-181 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T06:41:58.009466+00:00 |  |
| 182-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679443+00:00 | pre-commit gap — unattributed by the local hook |
| 225-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:29:17.982713+00:00 | pre-commit gap — unattributed by the local hook |
| 249-254 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:50:10.004251+00:00 | pre-commit gap — unattributed by the local hook |
