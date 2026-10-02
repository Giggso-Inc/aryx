# Attribution — src/aryx/cpq/engine.py

Last updated: 2026-09-30T08:05:11.453138+00:00
Total lines: 2401
Lines AI-generated: 293 (12.2%)
Lines human-typed: 0
Lines joint: 0
Lines unattributed: 2108
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-36 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329402+00:00 | pre-commit gap — unattributed by the local hook |
| 37-38 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:08:53.718549+00:00 |  |
| 39-50 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329450+00:00 | pre-commit gap — unattributed by the local hook |
| 51-51 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T07:56:30.565710+00:00 |  |
| 52-316 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329450+00:00 | pre-commit gap — unattributed by the local hook |
| 317-336 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T10:46:08.573307+00:00 |  |
| 337-700 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329450+00:00 | pre-commit gap — unattributed by the local hook |
| 701-713 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:14:04.545745+00:00 |  |
| 714-1117 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329498+00:00 | pre-commit gap — unattributed by the local hook |
| 1118-1121 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T04:16:32.200309+00:00 |  |
| 1122-1149 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329554+00:00 | pre-commit gap — unattributed by the local hook |
| 1150-1164 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:10:04.175398+00:00 |  |
| 1165-1371 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329616+00:00 | pre-commit gap — unattributed by the local hook |
| 1372-1383 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:13:49.007091+00:00 |  |
| 1384-1454 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329666+00:00 | pre-commit gap — unattributed by the local hook |
| 1455-1490 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T05:45:05.572270+00:00 |  |
| 1491-1596 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329718+00:00 | pre-commit gap — unattributed by the local hook |
| 1597-1609 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:15:05.126273+00:00 |  |
| 1610-1657 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329767+00:00 | pre-commit gap — unattributed by the local hook |
| 1658-1702 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:25:31.522974+00:00 |  |
| 1703-2124 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329814+00:00 | pre-commit gap — unattributed by the local hook |
| 2125-2139 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:29:47.430235+00:00 |  |
| 2140-2151 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329861+00:00 | pre-commit gap — unattributed by the local hook |
| 2152-2163 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:29:50.796461+00:00 |  |
| 2164-2257 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329909+00:00 | pre-commit gap — unattributed by the local hook |
| 2258-2288 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:28.690509+00:00 |  |
| 2289-2301 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329970+00:00 | pre-commit gap — unattributed by the local hook |
| 2302-2331 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:34.309982+00:00 |  |
| 2332-2337 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.330016+00:00 | pre-commit gap — unattributed by the local hook |
| 2338-2368 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:45.227943+00:00 |  |
| 2369-2375 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.330062+00:00 | pre-commit gap — unattributed by the local hook |
| 2376-2388 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:52.810810+00:00 |  |
| 2389-2401 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T11:26:48.815160+00:00 | pre-commit gap — unattributed by the local hook |
