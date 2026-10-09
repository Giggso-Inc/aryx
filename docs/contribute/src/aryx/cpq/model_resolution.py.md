# Attribution — src/aryx/cpq/model_resolution.py

Last updated: 2026-10-09T14:42:32.382135+00:00
Total lines: 382
Lines AI-generated: 47 (12.3%)
Lines human-typed: 42
Lines joint: 0
Lines unattributed: 293
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-33 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023378+00:00 | pre-commit gap — unattributed by the local hook |
| 34-34 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T10:10:01.417067+00:00 |  |
| 35-55 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023512+00:00 | pre-commit gap — unattributed by the local hook |
| 56-79 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:37:52.767807+00:00 |  |
| 80-81 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 82-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023635+00:00 | pre-commit gap — unattributed by the local hook |
| 96-98 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 99-101 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023757+00:00 | pre-commit gap — unattributed by the local hook |
| 102-114 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 115-123 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.023883+00:00 | pre-commit gap — unattributed by the local hook |
| 124-126 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:41:12.004240+00:00 |  |
| 127-144 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-09T14:38:00.455157+00:00 |  |
| 145-164 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024006+00:00 | pre-commit gap — unattributed by the local hook |
| 165-165 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.595328+00:00 |  |
| 166-166 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024130+00:00 | pre-commit gap — unattributed by the local hook |
| 167-167 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T07:44:18.595328+00:00 |  |
| 168-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T10:10:01.417067+00:00 |  |
| 169-169 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024282+00:00 | pre-commit gap — unattributed by the local hook |
| 170-170 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T10:10:01.417067+00:00 |  |
| 171-179 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024413+00:00 | pre-commit gap — unattributed by the local hook |
| 180-187 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T10:10:01.417067+00:00 |  |
| 188-192 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024543+00:00 | pre-commit gap — unattributed by the local hook |
| 193-193 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T10:10:01.417067+00:00 |  |
| 194-221 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.024682+00:00 | pre-commit gap — unattributed by the local hook |
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
| 284-382 | m.munir@giggso.com | — | — | — | — | — | 2026-10-09T14:42:32.025682+00:00 | pre-commit gap — unattributed by the local hook |
