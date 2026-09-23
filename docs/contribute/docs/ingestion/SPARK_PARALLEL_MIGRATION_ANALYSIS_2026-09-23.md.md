# Attribution — docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md

Last updated: 2026-09-23T17:51:30.550264+00:00
Total lines: 701
Lines AI-generated: 364 (51.9%)
Lines human-typed: 0
Lines joint: 0
Lines unattributed: 337
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-2 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.190667+00:00 | pre-commit gap — unattributed by the local hook |
| 3-11 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T17:43:25.167623+00:00 |  |
| 12-85 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.190828+00:00 | pre-commit gap — unattributed by the local hook |
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
| 635-687 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T17:43:13.638740+00:00 |  |
| 688-690 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T17:51:30.525384+00:00 | pre-commit gap — unattributed by the local hook |
| 691-701 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T17:43:38.673606+00:00 |  |
