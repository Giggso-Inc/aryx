# Attribution — src/aryx/store/oracle_cursor.py

Last updated: 2026-10-05T03:40:03.362250+00:00
Total lines: 428
Lines AI-generated: 71 (16.6%)
Lines human-typed: 65
Lines joint: 0
Lines unattributed: 292
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-9 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593216+00:00 | pre-commit gap — unattributed by the local hook |
| 10-14 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:38:16.873121+00:00 |  |
| 15-16 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 17-28 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593350+00:00 | pre-commit gap — unattributed by the local hook |
| 29-50 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 51-69 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T03:38:25.964773+00:00 |  |
| 70-82 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 83-102 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593421+00:00 | pre-commit gap — unattributed by the local hook |
| 103-123 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:18:27.912414+00:00 |  |
| 124-127 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593421+00:00 | pre-commit gap — unattributed by the local hook |
| 128-143 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T15:48:24.267327+00:00 |  |
| 144-166 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593421+00:00 | pre-commit gap — unattributed by the local hook |
| 167-169 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 170-174 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593489+00:00 | pre-commit gap — unattributed by the local hook |
| 175-176 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 177-177 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593556+00:00 | pre-commit gap — unattributed by the local hook |
| 178-178 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 179-180 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593623+00:00 | pre-commit gap — unattributed by the local hook |
| 181-182 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 183-183 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593699+00:00 | pre-commit gap — unattributed by the local hook |
| 184-185 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 186-206 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593769+00:00 | pre-commit gap — unattributed by the local hook |
| 207-207 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 208-213 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593836+00:00 | pre-commit gap — unattributed by the local hook |
| 214-216 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 217-217 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593901+00:00 | pre-commit gap — unattributed by the local hook |
| 218-221 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 222-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593966+00:00 | pre-commit gap — unattributed by the local hook |
| 225-226 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 227-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594035+00:00 | pre-commit gap — unattributed by the local hook |
| 228-229 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 230-243 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594102+00:00 | pre-commit gap — unattributed by the local hook |
| 244-248 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:18:43.468159+00:00 |  |
| 249-269 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594102+00:00 | pre-commit gap — unattributed by the local hook |
| 270-270 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 271-273 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594169+00:00 | pre-commit gap — unattributed by the local hook |
| 274-276 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 277-277 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594235+00:00 | pre-commit gap — unattributed by the local hook |
| 278-279 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 280-288 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594307+00:00 | pre-commit gap — unattributed by the local hook |
| 289-293 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:18:53.478319+00:00 |  |
| 294-335 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594307+00:00 | pre-commit gap — unattributed by the local hook |
| 336-397 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.855277+00:00 | pre-commit gap — unattributed by the local hook |
| 398-420 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T15:55:17.803448+00:00 | pre-commit gap — unattributed by the local hook |
| 421-428 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T03:40:03.092822+00:00 | pre-commit gap — unattributed by the local hook |
