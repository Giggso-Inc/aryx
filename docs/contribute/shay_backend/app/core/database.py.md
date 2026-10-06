# Attribution — shay_backend/app/core/database.py

Last updated: 2026-10-06T09:49:48.163008+00:00
Total lines: 187
Lines AI-generated: 46 (24.6%)
Lines human-typed: 23
Lines joint: 0
Lines unattributed: 118
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T03:22:56.476864+00:00 | pre-commit gap — unattributed by the local hook |
| 24-30 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T09:01:38.133314+00:00 |  |
| 31-33 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538396+00:00 | pre-commit gap — unattributed by the local hook |
| 34-34 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T03:59:32.114897+00:00 |  |
| 35-39 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T09:35:50.597783+00:00 |  |
| 40-59 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T03:59:32.114897+00:00 |  |
| 60-61 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:49:47.808374+00:00 | pre-commit gap — unattributed by the local hook |
| 62-71 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T03:22:56.477046+00:00 | pre-commit gap — unattributed by the local hook |
| 72-74 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-01T06:09:03.423974+00:00 |  |
| 75-86 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538454+00:00 | pre-commit gap — unattributed by the local hook |
| 87-97 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T09:01:45.491030+00:00 |  |
| 98-101 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538512+00:00 | pre-commit gap — unattributed by the local hook |
| 102-102 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T03:59:32.114897+00:00 |  |
| 103-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538569+00:00 | pre-commit gap — unattributed by the local hook |
| 105-106 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-01T06:08:56.908829+00:00 |  |
| 107-111 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-01T06:08:24.582753+00:00 |  |
| 112-115 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538626+00:00 | pre-commit gap — unattributed by the local hook |
| 116-116 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T03:59:32.114897+00:00 |  |
| 117-127 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538684+00:00 | pre-commit gap — unattributed by the local hook |
| 128-128 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T09:01:53.148826+00:00 |  |
| 129-164 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538740+00:00 | pre-commit gap — unattributed by the local hook |
| 165-169 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T09:01:10.620751+00:00 |  |
| 170-181 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T09:11:55.538797+00:00 | pre-commit gap — unattributed by the local hook |
| 182-188 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T09:01:17.096214+00:00 |  |
