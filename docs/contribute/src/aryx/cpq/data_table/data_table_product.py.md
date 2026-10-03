# Attribution — src/aryx/cpq/data_table/data_table_product.py

Last updated: 2026-10-03T09:08:41.882834+00:00
Total lines: 601
Lines AI-generated: 112 (18.6%)
Lines human-typed: 77
Lines joint: 0
Lines unattributed: 412
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-6 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T12:19:04.681045+00:00 | pre-commit gap — unattributed by the local hook |
| 7-45 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T13:30:07.841948+00:00 |  |
| 46-92 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T13:58:39.556974+00:00 | pre-commit gap — unattributed by the local hook |
| 93-153 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T12:19:04.681174+00:00 | pre-commit gap — unattributed by the local hook |
| 154-222 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T11:26:48.814940+00:00 | pre-commit gap — unattributed by the local hook |
| 223-239 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T10:45:52.230535+00:00 |  |
| 240-243 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567333+00:00 | pre-commit gap — unattributed by the local hook |
| 244-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 249-249 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567375+00:00 | pre-commit gap — unattributed by the local hook |
| 250-258 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 259-273 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567417+00:00 | pre-commit gap — unattributed by the local hook |
| 274-284 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T10:45:57.283770+00:00 |  |
| 285-287 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567459+00:00 | pre-commit gap — unattributed by the local hook |
| 288-298 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T11:58:13.514449+00:00 |  |
| 299-304 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567505+00:00 | pre-commit gap — unattributed by the local hook |
| 305-330 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 331-364 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T13:30:41.600725+00:00 |  |
| 365-386 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567549+00:00 | pre-commit gap — unattributed by the local hook |
| 387-394 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 395-398 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567592+00:00 | pre-commit gap — unattributed by the local hook |
| 399-399 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.959785+00:00 |  |
| 400-412 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567635+00:00 | pre-commit gap — unattributed by the local hook |
| 413-414 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.959785+00:00 |  |
| 415-426 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567677+00:00 | pre-commit gap — unattributed by the local hook |
| 427-430 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 431-432 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567734+00:00 | pre-commit gap — unattributed by the local hook |
| 433-435 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 436-439 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567778+00:00 | pre-commit gap — unattributed by the local hook |
| 440-443 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T12:19:04.681405+00:00 | pre-commit gap — unattributed by the local hook |
| 444-475 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567820+00:00 | pre-commit gap — unattributed by the local hook |
| 476-494 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 495-506 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567862+00:00 | pre-commit gap — unattributed by the local hook |
| 507-510 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T11:26:48.815092+00:00 | pre-commit gap — unattributed by the local hook |
| 511-601 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567904+00:00 | pre-commit gap — unattributed by the local hook |
