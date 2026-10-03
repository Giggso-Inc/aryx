# Attribution — src/aryx/api/file_ingest/file_ingest_api.py

Last updated: 2026-10-03T09:08:41.880866+00:00
Total lines: 220
Lines AI-generated: 24 (10.9%)
Lines human-typed: 50
Lines joint: 0
Lines unattributed: 146
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-2 | m.munir@giggso.com | — | — | — | — | — | 2026-09-30T08:41:58.668091+00:00 | pre-commit gap — unattributed by the local hook |
| 3-3 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T07:01:53.769789+00:00 |  |
| 4-8 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.117868+00:00 | pre-commit gap — unattributed by the local hook |
| 9-9 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.335717+00:00 |  |
| 10-24 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559715+00:00 | pre-commit gap — unattributed by the local hook |
| 25-25 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 26-32 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559787+00:00 | pre-commit gap — unattributed by the local hook |
| 33-33 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.335717+00:00 |  |
| 34-35 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559856+00:00 | pre-commit gap — unattributed by the local hook |
| 36-36 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 37-39 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559926+00:00 | pre-commit gap — unattributed by the local hook |
| 40-40 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.335717+00:00 |  |
| 41-78 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.118144+00:00 | pre-commit gap — unattributed by the local hook |
| 79-97 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T08:32:31.164975+00:00 |  |
| 98-99 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.559995+00:00 | pre-commit gap — unattributed by the local hook |
| 100-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 101-101 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560064+00:00 | pre-commit gap — unattributed by the local hook |
| 102-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 105-105 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560133+00:00 | pre-commit gap — unattributed by the local hook |
| 106-108 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 109-113 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560202+00:00 | pre-commit gap — unattributed by the local hook |
| 114-116 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 117-121 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560272+00:00 | pre-commit gap — unattributed by the local hook |
| 122-124 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 125-129 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560340+00:00 | pre-commit gap — unattributed by the local hook |
| 130-132 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 133-133 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560409+00:00 | pre-commit gap — unattributed by the local hook |
| 134-137 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 138-145 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560478+00:00 | pre-commit gap — unattributed by the local hook |
| 146-146 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 147-151 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560546+00:00 | pre-commit gap — unattributed by the local hook |
| 152-154 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 155-156 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560621+00:00 | pre-commit gap — unattributed by the local hook |
| 157-157 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 158-161 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T08:32:39.030879+00:00 |  |
| 162-166 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 167-191 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560699+00:00 | pre-commit gap — unattributed by the local hook |
| 192-195 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 196-197 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560769+00:00 | pre-commit gap — unattributed by the local hook |
| 198-198 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 199-200 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560838+00:00 | pre-commit gap — unattributed by the local hook |
| 201-210 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:51.872035+00:00 |  |
| 211-220 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.560908+00:00 | pre-commit gap — unattributed by the local hook |
