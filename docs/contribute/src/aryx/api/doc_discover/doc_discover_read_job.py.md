# Attribution — src/aryx/api/doc_discover/doc_discover_read_job.py

Last updated: 2026-10-03T10:28:44.419771+00:00
Total lines: 178
Lines AI-generated: 45 (25.3%)
Lines human-typed: 29
Lines joint: 0
Lines unattributed: 104
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-7 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T11:02:21.231305+00:00 |  |
| 8-11 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559045+00:00 | pre-commit gap — unattributed by the local hook |
| 12-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.869805+00:00 |  |
| 13-14 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559116+00:00 | pre-commit gap — unattributed by the local hook |
| 15-20 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T10:54:27.063117+00:00 |  |
| 21-22 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.869805+00:00 |  |
| 23-24 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940123+00:00 | pre-commit gap — unattributed by the local hook |
| 25-25 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:10:49.791777+00:00 |  |
| 26-38 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940269+00:00 | pre-commit gap — unattributed by the local hook |
| 39-58 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559187+00:00 | pre-commit gap — unattributed by the local hook |
| 59-65 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940360+00:00 | pre-commit gap — unattributed by the local hook |
| 66-73 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:11:10.650351+00:00 |  |
| 74-76 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940433+00:00 | pre-commit gap — unattributed by the local hook |
| 77-94 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T10:54:38.736013+00:00 |  |
| 95-95 | m.munir@giggso.com | — | — | — | — | — | 2026-09-30T12:35:49.140399+00:00 |  |
| 96-108 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559354+00:00 | pre-commit gap — unattributed by the local hook |
| 109-110 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.869805+00:00 |  |
| 111-120 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559423+00:00 | pre-commit gap — unattributed by the local hook |
| 121-127 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940487+00:00 | pre-commit gap — unattributed by the local hook |
| 128-131 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.869805+00:00 |  |
| 132-136 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T10:10:58.903761+00:00 |  |
| 137-137 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.279591+00:00 |  |
| 138-139 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940544+00:00 | pre-commit gap — unattributed by the local hook |
| 140-140 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:16:30.279591+00:00 |  |
| 141-141 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940602+00:00 | pre-commit gap — unattributed by the local hook |
| 142-151 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559492+00:00 | pre-commit gap — unattributed by the local hook |
| 152-161 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.869805+00:00 |  |
| 162-163 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559561+00:00 | pre-commit gap — unattributed by the local hook |
| 164-170 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.869805+00:00 |  |
| 171-173 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559631+00:00 | pre-commit gap — unattributed by the local hook |
| 174-178 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.940649+00:00 | pre-commit gap — unattributed by the local hook |
