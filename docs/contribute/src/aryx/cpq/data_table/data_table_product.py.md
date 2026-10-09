# Attribution — src/aryx/cpq/data_table/data_table_product.py

Last updated: 2026-10-09T12:55:04.509037+00:00
Total lines: 841
Lines AI-generated: 202 (24.0%)
Lines human-typed: 80
Lines joint: 0
Lines unattributed: 559
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-6 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T12:19:04.681045+00:00 | pre-commit gap — unattributed by the local hook |
| 7-45 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T13:30:07.841948+00:00 |  |
| 46-92 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T13:58:39.556974+00:00 | pre-commit gap — unattributed by the local hook |
| 93-141 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.746993+00:00 | pre-commit gap — unattributed by the local hook |
| 142-144 | m.munir@giggso.com | — | — | — | — | — | 2026-10-07T14:21:31.165367+00:00 |  |
| 145-146 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747082+00:00 | pre-commit gap — unattributed by the local hook |
| 147-148 | m.munir@giggso.com | — | — | — | — | — | 2026-10-07T14:21:31.165367+00:00 |  |
| 149-153 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747200+00:00 | pre-commit gap — unattributed by the local hook |
| 154-244 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T21:37:03.982967+00:00 |  |
| 245-273 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.570458+00:00 |  |
| 274-284 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T10:45:57.283770+00:00 |  |
| 285-287 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567459+00:00 | pre-commit gap — unattributed by the local hook |
| 288-298 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T11:58:13.514449+00:00 |  |
| 299-304 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567505+00:00 | pre-commit gap — unattributed by the local hook |
| 305-327 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747339+00:00 | pre-commit gap — unattributed by the local hook |
| 328-333 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:55:04.220183+00:00 | pre-commit gap — unattributed by the local hook |
| 334-334 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:19:06.672653+00:00 |  |
| 335-358 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T12:43:21.752052+00:00 |  |
| 359-363 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:55:04.220478+00:00 | pre-commit gap — unattributed by the local hook |
| 364-389 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T12:43:04.506662+00:00 |  |
| 390-394 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:53:06.041178+00:00 |  |
| 395-396 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:55:04.220604+00:00 | pre-commit gap — unattributed by the local hook |
| 397-404 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:53:06.041178+00:00 |  |
| 405-412 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:55:04.220698+00:00 | pre-commit gap — unattributed by the local hook |
| 413-414 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.959785+00:00 |  |
| 415-426 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567677+00:00 | pre-commit gap — unattributed by the local hook |
| 427-427 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T22:06:25.989856+00:00 | pre-commit gap — unattributed by the local hook |
| 428-430 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T15:40:27.173874+00:00 |  |
| 431-432 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567734+00:00 | pre-commit gap — unattributed by the local hook |
| 433-435 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.889938+00:00 |  |
| 436-439 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.567778+00:00 | pre-commit gap — unattributed by the local hook |
| 440-443 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T12:19:04.681405+00:00 | pre-commit gap — unattributed by the local hook |
| 444-461 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747591+00:00 | pre-commit gap — unattributed by the local hook |
| 462-476 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.570458+00:00 |  |
| 477-494 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747714+00:00 | pre-commit gap — unattributed by the local hook |
| 495-495 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.570458+00:00 |  |
| 496-499 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747838+00:00 | pre-commit gap — unattributed by the local hook |
| 500-501 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.570458+00:00 |  |
| 502-506 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.747961+00:00 | pre-commit gap — unattributed by the local hook |
| 507-510 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T11:26:48.815092+00:00 | pre-commit gap — unattributed by the local hook |
| 511-511 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.748274+00:00 | pre-commit gap — unattributed by the local hook |
| 512-512 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.570458+00:00 |  |
| 513-515 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.748488+00:00 | pre-commit gap — unattributed by the local hook |
| 516-520 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.570458+00:00 |  |
| 521-601 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.748697+00:00 | pre-commit gap — unattributed by the local hook |
| 602-636 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T22:06:25.990077+00:00 | pre-commit gap — unattributed by the local hook |
| 637-799 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:34:53.748906+00:00 | pre-commit gap — unattributed by the local hook |
| 800-841 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T12:55:04.220762+00:00 | pre-commit gap — unattributed by the local hook |
