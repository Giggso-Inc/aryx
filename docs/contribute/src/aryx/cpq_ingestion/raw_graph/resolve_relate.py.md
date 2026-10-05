# Attribution — src/aryx/cpq_ingestion/raw_graph/resolve_relate.py

Last updated: 2026-10-05T03:51:34.015215+00:00
Total lines: 486
Lines AI-generated: 178 (36.6%)
Lines human-typed: 83
Lines joint: 0
Lines unattributed: 225
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-19 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512646+00:00 | pre-commit gap — unattributed by the local hook |
| 20-23 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:56.527101+00:00 |  |
| 24-39 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:03.721605+00:00 |  |
| 40-40 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348507+00:00 | pre-commit gap — unattributed by the local hook |
| 41-42 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 43-43 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:21.766100+00:00 |  |
| 44-60 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 61-93 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:18:10.949642+00:00 |  |
| 94-98 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.344334+00:00 |  |
| 99-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512843+00:00 | pre-commit gap — unattributed by the local hook |
| 101-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.117355+00:00 |  |
| 105-105 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348569+00:00 | pre-commit gap — unattributed by the local hook |
| 106-119 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:14.098167+00:00 |  |
| 120-121 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T15:55:17.803155+00:00 | pre-commit gap — unattributed by the local hook |
| 122-122 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 123-156 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T15:47:54.079050+00:00 |  |
| 157-172 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T06:29:17.982447+00:00 | pre-commit gap — unattributed by the local hook |
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
| 240-242 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348699+00:00 | pre-commit gap — unattributed by the local hook |
| 243-246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 247-247 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513267+00:00 | pre-commit gap — unattributed by the local hook |
| 248-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 249-249 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T03:51:33.753779+00:00 | pre-commit gap — unattributed by the local hook |
| 250-262 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 263-268 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:51.553480+00:00 |  |
| 269-289 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 290-297 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:28.836053+00:00 |  |
| 298-305 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 306-349 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348758+00:00 | pre-commit gap — unattributed by the local hook |
| 350-351 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:55.752221+00:00 |  |
| 352-353 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348817+00:00 | pre-commit gap — unattributed by the local hook |
| 354-355 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 356-356 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348876+00:00 | pre-commit gap — unattributed by the local hook |
| 357-362 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T11:55:29.149304+00:00 | pre-commit gap — unattributed by the local hook |
| 363-395 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.854667+00:00 | pre-commit gap — unattributed by the local hook |
| 396-398 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:11:05.307291+00:00 |  |
| 399-399 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348934+00:00 | pre-commit gap — unattributed by the local hook |
| 400-417 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T14:09:16.113267+00:00 |  |
| 418-428 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348992+00:00 | pre-commit gap — unattributed by the local hook |
| 429-463 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T15:55:17.803240+00:00 | pre-commit gap — unattributed by the local hook |
| 464-470 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T03:51:33.753878+00:00 | pre-commit gap — unattributed by the local hook |
| 471-486 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:48:14.317141+00:00 |  |
