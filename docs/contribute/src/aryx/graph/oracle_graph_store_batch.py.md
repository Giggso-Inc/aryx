# Attribution — src/aryx/graph/oracle_graph_store_batch.py

Last updated: 2026-10-03T11:32:30.136605+00:00
Total lines: 329
Lines AI-generated: 152 (46.2%)
Lines human-typed: 19
Lines joint: 0
Lines unattributed: 158
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-7 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.102413+00:00 | pre-commit gap — unattributed by the local hook |
| 8-18 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T07:21:18.020235+00:00 |  |
| 19-20 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.102463+00:00 | pre-commit gap — unattributed by the local hook |
| 21-30 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.941841+00:00 | pre-commit gap — unattributed by the local hook |
| 31-31 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 32-47 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.941896+00:00 | pre-commit gap — unattributed by the local hook |
| 48-48 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 49-73 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:41:20.892023+00:00 |  |
| 74-79 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.941941+00:00 | pre-commit gap — unattributed by the local hook |
| 80-91 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 92-108 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.941985+00:00 | pre-commit gap — unattributed by the local hook |
| 109-110 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 111-111 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T11:31:38.917580+00:00 | pre-commit gap — unattributed by the local hook |
| 112-112 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 113-115 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T11:31:38.917637+00:00 | pre-commit gap — unattributed by the local hook |
| 116-116 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 117-167 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:41:37.161565+00:00 |  |
| 168-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.300089+00:00 |  |
| 169-170 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T11:31:38.917706+00:00 | pre-commit gap — unattributed by the local hook |
| 171-183 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942070+00:00 | pre-commit gap — unattributed by the local hook |
| 184-187 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T10:36:17.131722+00:00 | pre-commit gap — unattributed by the local hook |
| 188-199 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942113+00:00 | pre-commit gap — unattributed by the local hook |
| 200-202 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:07:49.160017+00:00 |  |
| 203-218 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942156+00:00 | pre-commit gap — unattributed by the local hook |
| 219-221 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:41:51.866911+00:00 |  |
| 222-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942156+00:00 | pre-commit gap — unattributed by the local hook |
| 225-225 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T10:36:17.131802+00:00 | pre-commit gap — unattributed by the local hook |
| 226-242 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.582891+00:00 | pre-commit gap — unattributed by the local hook |
| 243-265 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942202+00:00 | pre-commit gap — unattributed by the local hook |
| 266-278 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:07:54.836638+00:00 |  |
| 279-283 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942245+00:00 | pre-commit gap — unattributed by the local hook |
| 284-329 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T11:20:54.600017+00:00 |  |
