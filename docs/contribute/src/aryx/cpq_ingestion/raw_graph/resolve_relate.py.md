# Attribution — src/aryx/cpq_ingestion/raw_graph/resolve_relate.py

Last updated: 2026-10-04T13:52:28.066388+00:00
Total lines: 421
Lines AI-generated: 150 (35.6%)
Lines human-typed: 47
Lines joint: 0
Lines unattributed: 224
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512646+00:00 | pre-commit gap — unattributed by the local hook |
| 21-21 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 22-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512723+00:00 | pre-commit gap — unattributed by the local hook |
| 24-39 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:03.721605+00:00 |  |
| 40-40 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512790+00:00 | pre-commit gap — unattributed by the local hook |
| 41-60 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 61-93 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:18:10.949642+00:00 |  |
| 94-98 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 99-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512843+00:00 | pre-commit gap — unattributed by the local hook |
| 101-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.117355+00:00 |  |
| 105-105 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512901+00:00 | pre-commit gap — unattributed by the local hook |
| 106-119 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:14.098167+00:00 |  |
| 120-138 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:23.668948+00:00 |  |
| 139-142 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 143-143 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.854563+00:00 | pre-commit gap — unattributed by the local hook |
| 144-151 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513074+00:00 | pre-commit gap — unattributed by the local hook |
| 152-172 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:29:17.982447+00:00 | pre-commit gap — unattributed by the local hook |
| 173-175 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:50:10.003890+00:00 | pre-commit gap — unattributed by the local hook |
| 176-198 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:33:16.999557+00:00 |  |
| 199-219 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513123+00:00 | pre-commit gap — unattributed by the local hook |
| 220-222 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 223-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513171+00:00 | pre-commit gap — unattributed by the local hook |
| 228-228 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.874320+00:00 |  |
| 229-236 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513219+00:00 | pre-commit gap — unattributed by the local hook |
| 237-237 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T11:55:29.149230+00:00 | pre-commit gap — unattributed by the local hook |
| 238-238 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.854620+00:00 | pre-commit gap — unattributed by the local hook |
| 239-239 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:27:52.546728+00:00 |  |
| 240-242 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 243-263 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:11:20.417403+00:00 |  |
| 264-264 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 265-274 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513363+00:00 | pre-commit gap — unattributed by the local hook |
| 275-291 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:35:50.988512+00:00 |  |
| 292-294 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513411+00:00 | pre-commit gap — unattributed by the local hook |
| 295-296 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T11:50:53.407215+00:00 |  |
| 297-299 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513411+00:00 | pre-commit gap — unattributed by the local hook |
| 300-303 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 304-349 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513463+00:00 | pre-commit gap — unattributed by the local hook |
| 350-351 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:55.752221+00:00 |  |
| 352-356 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513463+00:00 | pre-commit gap — unattributed by the local hook |
| 357-362 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T11:55:29.149304+00:00 | pre-commit gap — unattributed by the local hook |
| 363-395 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.854667+00:00 | pre-commit gap — unattributed by the local hook |
| 396-398 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:11:05.307291+00:00 |  |
| 399-421 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.854718+00:00 | pre-commit gap — unattributed by the local hook |
