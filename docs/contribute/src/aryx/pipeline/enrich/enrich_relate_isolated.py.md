# Attribution — src/aryx/pipeline/enrich/enrich_relate_isolated.py

Last updated: 2026-10-03T09:08:41.908475+00:00
Total lines: 270
Lines AI-generated: 74 (27.4%)
Lines human-typed: 41
Lines joint: 0
Lines unattributed: 155
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-7 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T13:08:37.488381+00:00 | pre-commit gap — unattributed by the local hook |
| 8-27 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T13:00:11.579213+00:00 |  |
| 28-37 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T13:08:37.488532+00:00 | pre-commit gap — unattributed by the local hook |
| 38-40 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:12:37.829424+00:00 | pre-commit gap — unattributed by the local hook |
| 41-41 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.673531+00:00 |  |
| 42-56 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:00:38.633346+00:00 |  |
| 57-70 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586822+00:00 | pre-commit gap — unattributed by the local hook |
| 71-74 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 75-83 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586865+00:00 | pre-commit gap — unattributed by the local hook |
| 84-87 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 88-90 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586908+00:00 | pre-commit gap — unattributed by the local hook |
| 91-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 96-133 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586950+00:00 | pre-commit gap — unattributed by the local hook |
| 134-157 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:00:47.239786+00:00 |  |
| 158-170 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.586992+00:00 | pre-commit gap — unattributed by the local hook |
| 171-185 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T13:00:49.408273+00:00 |  |
| 186-191 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 192-192 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587048+00:00 | pre-commit gap — unattributed by the local hook |
| 193-197 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 198-205 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587091+00:00 | pre-commit gap — unattributed by the local hook |
| 206-206 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 207-213 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587136+00:00 | pre-commit gap — unattributed by the local hook |
| 214-225 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:12:37.829514+00:00 | pre-commit gap — unattributed by the local hook |
| 226-226 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587180+00:00 | pre-commit gap — unattributed by the local hook |
| 227-232 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 233-234 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587225+00:00 | pre-commit gap — unattributed by the local hook |
| 235-239 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 240-257 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587269+00:00 | pre-commit gap — unattributed by the local hook |
| 258-261 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.199439+00:00 |  |
| 262-270 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587313+00:00 | pre-commit gap — unattributed by the local hook |
