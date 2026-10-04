# Attribution — src/aryx/cpq_ingestion/raw_graph/resolve_relate.py

Last updated: 2026-10-04T10:55:53.727870+00:00
Total lines: 356
Lines AI-generated: 106 (29.8%)
Lines human-typed: 56
Lines joint: 0
Lines unattributed: 194
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512646+00:00 | pre-commit gap — unattributed by the local hook |
| 21-21 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 22-27 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512723+00:00 | pre-commit gap — unattributed by the local hook |
| 28-28 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 29-35 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:31:07.866883+00:00 |  |
| 36-36 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 37-40 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512790+00:00 | pre-commit gap — unattributed by the local hook |
| 41-60 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 61-93 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:18:10.949642+00:00 |  |
| 94-98 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 99-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512843+00:00 | pre-commit gap — unattributed by the local hook |
| 101-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.117355+00:00 |  |
| 105-108 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512901+00:00 | pre-commit gap — unattributed by the local hook |
| 109-113 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:26:17.884365+00:00 |  |
| 114-119 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512959+00:00 | pre-commit gap — unattributed by the local hook |
| 120-122 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.117355+00:00 |  |
| 123-123 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.581594+00:00 | pre-commit gap — unattributed by the local hook |
| 124-128 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513020+00:00 | pre-commit gap — unattributed by the local hook |
| 129-143 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:26:28.224752+00:00 |  |
| 144-151 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513074+00:00 | pre-commit gap — unattributed by the local hook |
| 152-172 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:29:17.982447+00:00 | pre-commit gap — unattributed by the local hook |
| 173-175 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:50:10.003890+00:00 | pre-commit gap — unattributed by the local hook |
| 176-198 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:33:16.999557+00:00 |  |
| 199-219 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513123+00:00 | pre-commit gap — unattributed by the local hook |
| 220-222 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 223-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513171+00:00 | pre-commit gap — unattributed by the local hook |
| 228-228 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.874320+00:00 |  |
| 229-236 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513219+00:00 | pre-commit gap — unattributed by the local hook |
| 237-242 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:31:02.408285+00:00 |  |
| 243-243 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 244-244 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:27:52.546728+00:00 |  |
| 245-246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:41:06.497613+00:00 | pre-commit gap — unattributed by the local hook |
| 247-247 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513267+00:00 | pre-commit gap — unattributed by the local hook |
| 248-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 249-254 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513315+00:00 | pre-commit gap — unattributed by the local hook |
| 255-264 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 265-274 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513363+00:00 | pre-commit gap — unattributed by the local hook |
| 275-291 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:35:50.988512+00:00 |  |
| 292-299 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513411+00:00 | pre-commit gap — unattributed by the local hook |
| 300-303 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 304-356 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513463+00:00 | pre-commit gap — unattributed by the local hook |
