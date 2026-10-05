# Attribution — src/aryx/cpq_ingestion/raw_graph/resolve_relate.py

Last updated: 2026-10-05T11:09:05.148513+00:00
Total lines: 509
Lines AI-generated: 146 (28.7%)
Lines human-typed: 154
Lines joint: 0
Lines unattributed: 209
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-19 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512646+00:00 | pre-commit gap — unattributed by the local hook |
| 20-23 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:56.527101+00:00 |  |
| 24-24 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639037+00:00 | pre-commit gap — unattributed by the local hook |
| 25-26 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 27-27 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 28-28 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 29-29 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639125+00:00 | pre-commit gap — unattributed by the local hook |
| 30-30 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 31-31 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 32-34 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639200+00:00 | pre-commit gap — unattributed by the local hook |
| 35-35 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 36-37 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639269+00:00 | pre-commit gap — unattributed by the local hook |
| 38-38 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 39-43 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T10:43:14.022374+00:00 |  |
| 44-44 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 45-60 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639338+00:00 | pre-commit gap — unattributed by the local hook |
| 61-65 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 66-66 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639406+00:00 | pre-commit gap — unattributed by the local hook |
| 67-74 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:52:41.014393+00:00 |  |
| 75-77 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.117355+00:00 |  |
| 78-98 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.532646+00:00 | pre-commit gap — unattributed by the local hook |
| 99-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.512843+00:00 | pre-commit gap — unattributed by the local hook |
| 101-101 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639475+00:00 | pre-commit gap — unattributed by the local hook |
| 102-102 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 103-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639542+00:00 | pre-commit gap — unattributed by the local hook |
| 105-105 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348569+00:00 | pre-commit gap — unattributed by the local hook |
| 106-119 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:14.098167+00:00 |  |
| 120-121 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T15:55:17.803155+00:00 | pre-commit gap — unattributed by the local hook |
| 122-122 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 123-156 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T15:47:54.079050+00:00 |  |
| 157-160 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 161-172 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639611+00:00 | pre-commit gap — unattributed by the local hook |
| 173-175 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 176-198 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:33:16.999557+00:00 |  |
| 199-209 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639679+00:00 | pre-commit gap — unattributed by the local hook |
| 210-218 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 219-219 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639747+00:00 | pre-commit gap — unattributed by the local hook |
| 220-223 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 224-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639822+00:00 | pre-commit gap — unattributed by the local hook |
| 228-228 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:29.232199+00:00 |  |
| 229-236 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513219+00:00 | pre-commit gap — unattributed by the local hook |
| 237-237 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T11:55:29.149230+00:00 | pre-commit gap — unattributed by the local hook |
| 238-238 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.854620+00:00 | pre-commit gap — unattributed by the local hook |
| 239-239 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:27:52.546728+00:00 |  |
| 240-242 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348699+00:00 | pre-commit gap — unattributed by the local hook |
| 243-246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 247-247 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513267+00:00 | pre-commit gap — unattributed by the local hook |
| 248-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.039856+00:00 |  |
| 249-249 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T03:51:33.753779+00:00 | pre-commit gap — unattributed by the local hook |
| 250-262 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.532911+00:00 | pre-commit gap — unattributed by the local hook |
| 263-268 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:51.553480+00:00 |  |
| 269-271 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 272-274 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639891+00:00 | pre-commit gap — unattributed by the local hook |
| 275-289 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 290-297 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:47:28.836053+00:00 |  |
| 298-349 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 350-351 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:10:55.752221+00:00 |  |
| 352-358 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 359-359 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.639961+00:00 | pre-commit gap — unattributed by the local hook |
| 360-360 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 361-364 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640032+00:00 | pre-commit gap — unattributed by the local hook |
| 365-365 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 366-371 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640125+00:00 | pre-commit gap — unattributed by the local hook |
| 372-381 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 382-391 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640208+00:00 | pre-commit gap — unattributed by the local hook |
| 392-395 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 396-398 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:11:05.307291+00:00 |  |
| 399-400 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 401-401 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:10:03.735266+00:00 |  |
| 402-424 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T10:43:23.650599+00:00 |  |
| 425-428 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.348992+00:00 | pre-commit gap — unattributed by the local hook |
| 429-453 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640287+00:00 | pre-commit gap — unattributed by the local hook |
| 454-454 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 455-456 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640366+00:00 | pre-commit gap — unattributed by the local hook |
| 457-460 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 461-465 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640445+00:00 | pre-commit gap — unattributed by the local hook |
| 466-470 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 471-486 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:48:14.317141+00:00 |  |
| 487-488 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.791172+00:00 |  |
| 489-509 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640524+00:00 | pre-commit gap — unattributed by the local hook |
