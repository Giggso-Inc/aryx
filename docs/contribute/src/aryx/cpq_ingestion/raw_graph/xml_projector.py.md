# Attribution — src/aryx/cpq_ingestion/raw_graph/xml_projector.py

Last updated: 2026-10-04T06:29:18.203623+00:00
Total lines: 248
Lines AI-generated: 91 (36.7%)
Lines human-typed: 48
Lines joint: 0
Lines unattributed: 109
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-10 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T07:35:26.039066+00:00 | pre-commit gap — unattributed by the local hook |
| 11-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679088+00:00 | pre-commit gap — unattributed by the local hook |
| 13-17 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:47:33.017976+00:00 |  |
| 18-18 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679157+00:00 | pre-commit gap — unattributed by the local hook |
| 19-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:53:53.791207+00:00 | pre-commit gap — unattributed by the local hook |
| 21-24 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T06:18:41.998906+00:00 |  |
| 25-31 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
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
| 161-162 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.123811+00:00 |  |
| 163-177 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T06:19:26.387547+00:00 |  |
| 178-178 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:29:17.982620+00:00 | pre-commit gap — unattributed by the local hook |
| 179-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T04:57:38.679443+00:00 | pre-commit gap — unattributed by the local hook |
| 225-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:29:17.982713+00:00 | pre-commit gap — unattributed by the local hook |
