# Attribution — tests/cpq_ingestion/test_resolve_and_relate_raw_graph.py

Last updated: 2026-10-05T11:56:03.736705+00:00
Total lines: 823
Lines AI-generated: 177 (21.5%)
Lines human-typed: 160
Lines joint: 0
Lines unattributed: 486
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-16 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T05:56:43.535144+00:00 | pre-commit gap — unattributed by the local hook |
| 17-21 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T10:43:45.422898+00:00 |  |
| 22-141 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.536511+00:00 | pre-commit gap — unattributed by the local hook |
| 142-142 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640603+00:00 | pre-commit gap — unattributed by the local hook |
| 143-143 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T11:56:03.470268+00:00 | pre-commit gap — unattributed by the local hook |
| 144-148 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.944901+00:00 |  |
| 149-190 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T11:49:33.934987+00:00 |  |
| 191-193 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.944901+00:00 |  |
| 194-211 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640757+00:00 | pre-commit gap — unattributed by the local hook |
| 212-228 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:29:19.373531+00:00 | pre-commit gap — unattributed by the local hook |
| 229-257 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:41:06.497911+00:00 | pre-commit gap — unattributed by the local hook |
| 258-269 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T05:56:43.542999+00:00 | pre-commit gap — unattributed by the local hook |
| 270-282 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:41:06.497977+00:00 | pre-commit gap — unattributed by the local hook |
| 283-323 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:13:12.394720+00:00 | pre-commit gap — unattributed by the local hook |
| 324-329 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:34:17.138967+00:00 |  |
| 330-337 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:13:12.394720+00:00 | pre-commit gap — unattributed by the local hook |
| 338-370 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:29:19.373586+00:00 | pre-commit gap — unattributed by the local hook |
| 371-421 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640841+00:00 | pre-commit gap — unattributed by the local hook |
| 422-434 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T14:23:29.350364+00:00 | pre-commit gap — unattributed by the local hook |
| 435-471 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640920+00:00 | pre-commit gap — unattributed by the local hook |
| 472-473 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.944901+00:00 |  |
| 474-501 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:15:40.535626+00:00 |  |
| 502-528 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.944901+00:00 |  |
| 529-548 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:15:56.455601+00:00 |  |
| 549-671 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.944901+00:00 |  |
| 672-747 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:47:06.419024+00:00 |  |
| 748-785 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T10:59:11.640998+00:00 | pre-commit gap — unattributed by the local hook |
| 786-823 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T11:56:03.470372+00:00 | pre-commit gap — unattributed by the local hook |
