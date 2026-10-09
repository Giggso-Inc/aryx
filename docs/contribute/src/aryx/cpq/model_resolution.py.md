# Attribution — src/aryx/cpq/model_resolution.py

Last updated: 2026-10-09T15:16:04.373880+00:00
Total lines: 443
Lines AI-generated: 109 (24.6%)
Lines human-typed: 41
Lines joint: 0
Lines unattributed: 293
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-19 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023378+00:00 | pre-commit gap — unattributed by the local hook |
| 20-24 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:57:05.074556+00:00 |  |
| 25-33 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023378+00:00 | pre-commit gap — unattributed by the local hook |
| 34-34 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T10:10:01.417067+00:00 |  |
| 35-55 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023512+00:00 | pre-commit gap — unattributed by the local hook |
| 56-101 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:56:35.678719+00:00 |  |
| 102-114 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 115-123 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023883+00:00 | pre-commit gap — unattributed by the local hook |
| 124-143 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 144-144 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T15:16:04.097869+00:00 | pre-commit gap — unattributed by the local hook |
| 145-156 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024006+00:00 | pre-commit gap — unattributed by the local hook |
| 157-205 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T15:07:58.885491+00:00 |  |
| 206-221 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024682+00:00 | pre-commit gap — unattributed by the local hook |
| 222-222 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:40:58.594826+00:00 |  |
| 223-225 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024811+00:00 | pre-commit gap — unattributed by the local hook |
| 226-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-08T07:32:20.332579+00:00 |  |
| 228-249 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024934+00:00 | pre-commit gap — unattributed by the local hook |
| 250-253 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:36:03.111101+00:00 |  |
| 254-260 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025141+00:00 | pre-commit gap — unattributed by the local hook |
| 261-262 | m.munir@giggso.com | — | — | — | — | — | 2026-10-08T07:32:20.332579+00:00 |  |
| 263-265 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025296+00:00 | pre-commit gap — unattributed by the local hook |
| 266-266 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 267-268 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025431+00:00 | pre-commit gap — unattributed by the local hook |
| 269-269 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:36:07.642954+00:00 |  |
| 270-282 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025560+00:00 | pre-commit gap — unattributed by the local hook |
| 283-283 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 284-313 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025682+00:00 | pre-commit gap — unattributed by the local hook |
| 314-316 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:57:14.127449+00:00 |  |
| 317-331 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025682+00:00 | pre-commit gap — unattributed by the local hook |
| 332-332 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:57:18.476125+00:00 |  |
| 333-382 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025682+00:00 | pre-commit gap — unattributed by the local hook |
| 383-431 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T15:02:21.426248+00:00 | pre-commit gap — unattributed by the local hook |
| 432-443 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T15:16:04.098137+00:00 | pre-commit gap — unattributed by the local hook |
