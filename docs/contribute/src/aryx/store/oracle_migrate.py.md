# Attribution — src/aryx/store/oracle_migrate.py

Last updated: 2026-10-05T05:17:22.451644+00:00
Total lines: 490
Lines AI-generated: 154 (31.4%)
Lines human-typed: 27
Lines joint: 0
Lines unattributed: 309
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-3 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.534806+00:00 | pre-commit gap — unattributed by the local hook |
| 4-9 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:49:16.169594+00:00 |  |
| 10-13 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.534890+00:00 | pre-commit gap — unattributed by the local hook |
| 14-18 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T04:53:38.422834+00:00 |  |
| 19-56 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.534973+00:00 | pre-commit gap — unattributed by the local hook |
| 57-57 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T04:53:38.422834+00:00 |  |
| 58-61 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535062+00:00 | pre-commit gap — unattributed by the local hook |
| 62-92 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:44:12.148888+00:00 |  |
| 93-93 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535162+00:00 | pre-commit gap — unattributed by the local hook |
| 94-98 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T03:40:03.093020+00:00 | pre-commit gap — unattributed by the local hook |
| 99-103 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535247+00:00 | pre-commit gap — unattributed by the local hook |
| 104-107 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T04:53:38.422834+00:00 |  |
| 108-121 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535333+00:00 | pre-commit gap — unattributed by the local hook |
| 122-153 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:34:51.823437+00:00 |  |
| 154-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535418+00:00 | pre-commit gap — unattributed by the local hook |
| 169-178 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:44:48.201496+00:00 |  |
| 179-181 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535529+00:00 | pre-commit gap — unattributed by the local hook |
| 182-192 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T03:40:03.093122+00:00 | pre-commit gap — unattributed by the local hook |
| 193-205 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535646+00:00 | pre-commit gap — unattributed by the local hook |
| 206-211 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T04:53:38.422834+00:00 |  |
| 212-221 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:11:58.435714+00:00 |  |
| 222-256 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535768+00:00 | pre-commit gap — unattributed by the local hook |
| 257-258 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T04:53:38.422834+00:00 |  |
| 259-268 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.535887+00:00 | pre-commit gap — unattributed by the local hook |
| 269-311 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T05:14:44.571911+00:00 |  |
| 312-333 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:17:22.198105+00:00 | pre-commit gap — unattributed by the local hook |
| 334-381 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.536140+00:00 | pre-commit gap — unattributed by the local hook |
| 382-392 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:44:39.310982+00:00 |  |
| 393-396 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:17:22.198211+00:00 | pre-commit gap — unattributed by the local hook |
| 397-407 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T05:14:50.906776+00:00 |  |
| 408-413 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:17:22.198299+00:00 | pre-commit gap — unattributed by the local hook |
| 414-422 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T04:53:38.422834+00:00 |  |
| 423-473 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.536378+00:00 | pre-commit gap — unattributed by the local hook |
| 474-490 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:17:22.198379+00:00 | pre-commit gap — unattributed by the local hook |
