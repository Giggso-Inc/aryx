# Attribution — src/aryx/pipeline/doc_discovery/doc_discovery_fk.py

Last updated: 2026-10-03T09:08:41.889365+00:00
Total lines: 635
Lines AI-generated: 273 (43.0%)
Lines human-typed: 44
Lines joint: 0
Lines unattributed: 318
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-19 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585713+00:00 | pre-commit gap — unattributed by the local hook |
| 20-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 21-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585759+00:00 | pre-commit gap — unattributed by the local hook |
| 24-61 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T12:32:07.890682+00:00 |  |
| 62-106 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585803+00:00 | pre-commit gap — unattributed by the local hook |
| 107-204 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T12:32:31.918153+00:00 |  |
| 205-205 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585847+00:00 | pre-commit gap — unattributed by the local hook |
| 206-342 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T12:35:04.283009+00:00 |  |
| 343-358 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585890+00:00 | pre-commit gap — unattributed by the local hook |
| 359-363 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 364-440 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585933+00:00 | pre-commit gap — unattributed by the local hook |
| 441-445 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 446-447 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585977+00:00 | pre-commit gap — unattributed by the local hook |
| 448-451 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 452-489 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586020+00:00 | pre-commit gap — unattributed by the local hook |
| 490-493 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 494-501 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586064+00:00 | pre-commit gap — unattributed by the local hook |
| 502-505 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 506-507 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586106+00:00 | pre-commit gap — unattributed by the local hook |
| 508-509 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 510-515 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586149+00:00 | pre-commit gap — unattributed by the local hook |
| 516-518 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 519-538 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586194+00:00 | pre-commit gap — unattributed by the local hook |
| 539-541 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 542-569 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586242+00:00 | pre-commit gap — unattributed by the local hook |
| 570-571 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 572-592 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586286+00:00 | pre-commit gap — unattributed by the local hook |
| 593-596 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 597-625 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586328+00:00 | pre-commit gap — unattributed by the local hook |
| 626-629 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 630-631 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586371+00:00 | pre-commit gap — unattributed by the local hook |
| 632-634 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.179516+00:00 |  |
| 635-635 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586413+00:00 | pre-commit gap — unattributed by the local hook |
