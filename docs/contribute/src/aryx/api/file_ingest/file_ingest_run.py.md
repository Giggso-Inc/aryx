# Attribution — src/aryx/api/file_ingest/file_ingest_run.py

Last updated: 2026-10-03T10:28:44.417157+00:00
Total lines: 564
Lines AI-generated: 74 (13.1%)
Lines human-typed: 127
Lines joint: 0
Lines unattributed: 363
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-6 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T07:01:22.301100+00:00 |  |
| 7-8 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:47:48.084896+00:00 | pre-commit gap — unattributed by the local hook |
| 9-13 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:57:38.808048+00:00 |  |
| 14-14 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.118394+00:00 | pre-commit gap — unattributed by the local hook |
| 15-19 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560978+00:00 | pre-commit gap — unattributed by the local hook |
| 20-22 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 23-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561048+00:00 | pre-commit gap — unattributed by the local hook |
| 24-26 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T06:42:43.719823+00:00 |  |
| 27-29 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.118473+00:00 | pre-commit gap — unattributed by the local hook |
| 30-30 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:58:58.459931+00:00 |  |
| 31-31 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.344441+00:00 |  |
| 32-32 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:40:06.196681+00:00 |  |
| 33-37 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:47:48.085119+00:00 | pre-commit gap — unattributed by the local hook |
| 38-41 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T07:01:32.219701+00:00 |  |
| 42-44 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561117+00:00 | pre-commit gap — unattributed by the local hook |
| 45-50 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 51-74 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561186+00:00 | pre-commit gap — unattributed by the local hook |
| 75-119 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:23:19.234329+00:00 |  |
| 120-124 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 125-135 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561255+00:00 | pre-commit gap — unattributed by the local hook |
| 136-136 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 137-137 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:58:58.459931+00:00 |  |
| 138-142 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T08:32:24.381695+00:00 |  |
| 143-148 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 149-152 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561325+00:00 | pre-commit gap — unattributed by the local hook |
| 153-159 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 160-166 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561394+00:00 | pre-commit gap — unattributed by the local hook |
| 167-167 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 168-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561462+00:00 | pre-commit gap — unattributed by the local hook |
| 169-169 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:41:27.520174+00:00 |  |
| 170-172 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 173-174 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561536+00:00 | pre-commit gap — unattributed by the local hook |
| 175-186 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 187-190 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561606+00:00 | pre-commit gap — unattributed by the local hook |
| 191-196 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 197-207 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561675+00:00 | pre-commit gap — unattributed by the local hook |
| 208-213 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 214-219 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561755+00:00 | pre-commit gap — unattributed by the local hook |
| 220-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.344441+00:00 |  |
| 225-246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561825+00:00 | pre-commit gap — unattributed by the local hook |
| 247-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 249-262 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561894+00:00 | pre-commit gap — unattributed by the local hook |
| 263-266 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 267-318 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.561965+00:00 | pre-commit gap — unattributed by the local hook |
| 319-327 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 328-332 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:10:35.436236+00:00 |  |
| 333-350 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940720+00:00 | pre-commit gap — unattributed by the local hook |
| 351-355 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 356-412 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562104+00:00 | pre-commit gap — unattributed by the local hook |
| 413-414 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 415-426 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562159+00:00 | pre-commit gap — unattributed by the local hook |
| 427-430 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.344441+00:00 |  |
| 431-464 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562205+00:00 | pre-commit gap — unattributed by the local hook |
| 465-470 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 471-496 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562250+00:00 | pre-commit gap — unattributed by the local hook |
| 497-500 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 501-518 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562293+00:00 | pre-commit gap — unattributed by the local hook |
| 519-519 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 520-521 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562340+00:00 | pre-commit gap — unattributed by the local hook |
| 522-528 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 529-530 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562383+00:00 | pre-commit gap — unattributed by the local hook |
| 531-536 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 537-542 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562425+00:00 | pre-commit gap — unattributed by the local hook |
| 543-547 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 548-549 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562467+00:00 | pre-commit gap — unattributed by the local hook |
| 550-556 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.875817+00:00 |  |
| 557-563 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.562509+00:00 | pre-commit gap — unattributed by the local hook |
| 564-564 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940787+00:00 | pre-commit gap — unattributed by the local hook |
