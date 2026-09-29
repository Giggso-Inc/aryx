# Attribution — src/aryx/cpq/model_policy.py

Last updated: 2026-09-29T06:20:32.719308+00:00
Total lines: 577
Lines AI-generated: 243 (42.1%)
Lines human-typed: 0
Lines joint: 0
Lines unattributed: 334
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-23 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T15:44:45.000302+00:00 | pre-commit gap — unattributed by the local hook |
| 24-38 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T05:45:34.688022+00:00 | pre-commit gap — unattributed by the local hook |
| 39-48 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T07:32:04.054299+00:00 | pre-commit gap — unattributed by the local hook |
| 49-81 | m.munir@giggso.com | — | — | — | — | — | 2026-09-25T15:44:45.000391+00:00 | pre-commit gap — unattributed by the local hook |
| 82-89 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T05:45:34.688088+00:00 | pre-commit gap — unattributed by the local hook |
| 90-115 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T05:43:53.444980+00:00 |  |
| 116-118 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T06:47:41.686444+00:00 | pre-commit gap — unattributed by the local hook |
| 119-145 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T03:33:56.689070+00:00 |  |
| 146-153 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T06:47:41.686495+00:00 | pre-commit gap — unattributed by the local hook |
| 154-171 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T04:15:42.221567+00:00 |  |
| 172-177 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T06:21:06.197834+00:00 | pre-commit gap — unattributed by the local hook |
| 178-188 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T06:20:32.659967+00:00 | pre-commit gap — unattributed by the local hook |
| 189-199 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T05:43:59.671386+00:00 |  |
| 200-216 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T06:20:32.660047+00:00 | pre-commit gap — unattributed by the local hook |
| 217-227 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T06:21:06.197905+00:00 | pre-commit gap — unattributed by the local hook |
| 228-231 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T06:47:41.686546+00:00 | pre-commit gap — unattributed by the local hook |
| 232-243 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T03:34:01.653420+00:00 |  |
| 244-268 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T04:05:08.467084+00:00 | pre-commit gap — unattributed by the local hook |
| 269-280 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T04:15:47.549250+00:00 |  |
| 281-284 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T06:47:41.686595+00:00 | pre-commit gap — unattributed by the local hook |
| 285-307 | m.munir@giggso.com | — | — | — | — | — | 2026-09-28T07:32:04.054386+00:00 | pre-commit gap — unattributed by the local hook |
| 308-318 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T05:44:05.665269+00:00 |  |
| 319-344 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T06:20:32.660124+00:00 | pre-commit gap — unattributed by the local hook |
| 345-347 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T04:05:08.467170+00:00 | pre-commit gap — unattributed by the local hook |
| 348-383 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T03:34:11.917451+00:00 |  |
| 384-414 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T04:05:08.467252+00:00 | pre-commit gap — unattributed by the local hook |
| 415-419 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T05:40:15.332828+00:00 | pre-commit gap — unattributed by the local hook |
| 420-457 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T04:15:56.490761+00:00 |  |
| 458-488 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T05:40:15.332901+00:00 | pre-commit gap — unattributed by the local hook |
| 489-494 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T06:20:32.660205+00:00 | pre-commit gap — unattributed by the local hook |
| 495-546 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T05:44:17.048928+00:00 |  |
| 547-577 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T06:20:32.660287+00:00 | pre-commit gap — unattributed by the local hook |
