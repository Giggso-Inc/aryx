# Attribution — docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md

Last updated: 2026-09-24T11:19:39.658683+00:00
Total lines: 1134
Lines AI-generated: 573 (50.5%)
Lines human-typed: 0
Lines joint: 0
Lines unattributed: 561
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-2 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.190667+00:00 | pre-commit gap — unattributed by the local hook |
| 3-7 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.101683+00:00 | pre-commit gap — unattributed by the local hook |
| 8-9 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.190828+00:00 | pre-commit gap — unattributed by the local hook |
| 10-23 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T10:27:58.985723+00:00 |  |
| 24-85 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.190828+00:00 | pre-commit gap — unattributed by the local hook |
| 86-133 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T11:02:04.285069+00:00 |  |
| 134-163 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.190964+00:00 | pre-commit gap — unattributed by the local hook |
| 164-164 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T11:02:13.403481+00:00 |  |
| 165-170 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.191091+00:00 | pre-commit gap — unattributed by the local hook |
| 171-182 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T12:49:06.347691+00:00 |  |
| 183-197 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.191218+00:00 | pre-commit gap — unattributed by the local hook |
| 198-198 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T11:02:17.054615+00:00 |  |
| 199-287 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.191344+00:00 | pre-commit gap — unattributed by the local hook |
| 288-367 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T12:48:54.097442+00:00 |  |
| 368-376 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.191465+00:00 | pre-commit gap — unattributed by the local hook |
| 377-386 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T13:49:06.369424+00:00 |  |
| 387-424 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.191601+00:00 | pre-commit gap — unattributed by the local hook |
| 425-479 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T13:49:22.925396+00:00 |  |
| 480-481 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.191736+00:00 | pre-commit gap — unattributed by the local hook |
| 482-550 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T14:14:36.123060+00:00 |  |
| 551-556 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T14:15:46.850460+00:00 | pre-commit gap — unattributed by the local hook |
| 557-565 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T17:42:56.336236+00:00 |  |
| 566-579 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T14:15:46.850460+00:00 | pre-commit gap — unattributed by the local hook |
| 580-585 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T14:14:46.836603+00:00 |  |
| 586-634 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T17:51:30.525143+00:00 | pre-commit gap — unattributed by the local hook |
| 635-654 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.101828+00:00 | pre-commit gap — unattributed by the local hook |
| 655-658 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T17:30:35.738675+00:00 | pre-commit gap — unattributed by the local hook |
| 659-687 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.101903+00:00 | pre-commit gap — unattributed by the local hook |
| 688-690 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T17:51:30.525384+00:00 | pre-commit gap — unattributed by the local hook |
| 691-697 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.101964+00:00 | pre-commit gap — unattributed by the local hook |
| 698-707 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T07:24:33.017561+00:00 |  |
| 708-720 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.102022+00:00 | pre-commit gap — unattributed by the local hook |
| 721-721 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T07:24:37.480174+00:00 |  |
| 722-762 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.102085+00:00 | pre-commit gap — unattributed by the local hook |
| 763-800 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T10:36:17.130857+00:00 | pre-commit gap — unattributed by the local hook |
| 801-850 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T10:27:29.566347+00:00 |  |
| 851-859 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.102210+00:00 | pre-commit gap — unattributed by the local hook |
| 860-878 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T09:16:41.754063+00:00 |  |
| 879-893 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T09:18:38.102260+00:00 | pre-commit gap — unattributed by the local hook |
| 894-903 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T10:36:17.131061+00:00 | pre-commit gap — unattributed by the local hook |
| 904-923 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T11:17:10.563688+00:00 | pre-commit gap — unattributed by the local hook |
| 924-1079 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T11:13:25.041541+00:00 |  |
| 1080-1102 | m.munir@giggso.com | — | — | — | — | — | 2026-09-24T11:17:10.563906+00:00 | pre-commit gap — unattributed by the local hook |
| 1103-1134 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T11:13:42.364223+00:00 |  |
