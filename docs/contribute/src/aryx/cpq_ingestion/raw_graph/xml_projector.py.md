# Attribution — src/aryx/cpq_ingestion/raw_graph/xml_projector.py

Last updated: 2026-10-04T04:57:38.895610+00:00
Total lines: 224
Lines AI-generated: 59 (26.3%)
Lines human-typed: 71
Lines joint: 0
Lines unattributed: 94
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-10 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.039066+00:00 | pre-commit gap — unattributed by the local hook |
| 11-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679088+00:00 | pre-commit gap — unattributed by the local hook |
| 13-17 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:47:33.017976+00:00 |  |
| 18-18 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679157+00:00 | pre-commit gap — unattributed by the local hook |
| 19-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:53:53.791207+00:00 | pre-commit gap — unattributed by the local hook |
| 21-21 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.581911+00:00 | pre-commit gap — unattributed by the local hook |
| 22-31 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 32-39 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.581953+00:00 | pre-commit gap — unattributed by the local hook |
| 40-43 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:33:36.713738+00:00 |  |
| 44-44 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.039581+00:00 | pre-commit gap — unattributed by the local hook |
| 45-46 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:33:36.713738+00:00 |  |
| 47-47 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.040278+00:00 | pre-commit gap — unattributed by the local hook |
| 48-94 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T08:44:58.784176+00:00 |  |
| 95-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.581995+00:00 | pre-commit gap — unattributed by the local hook |
| 96-112 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 113-113 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.582037+00:00 | pre-commit gap — unattributed by the local hook |
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
| 164-166 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:47:38.006961+00:00 |  |
| 167-174 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679379+00:00 | pre-commit gap — unattributed by the local hook |
| 175-178 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:47:43.762481+00:00 |  |
| 179-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679443+00:00 | pre-commit gap — unattributed by the local hook |
