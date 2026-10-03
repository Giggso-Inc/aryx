# Attribution — src/aryx/store/oracle_cursor.py

Last updated: 2026-10-03T09:08:41.886818+00:00
Total lines: 335
Lines AI-generated: 17 (5.1%)
Lines human-typed: 70
Lines joint: 0
Lines unattributed: 248
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-10 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593216+00:00 | pre-commit gap — unattributed by the local hook |
| 11-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 13-13 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593283+00:00 | pre-commit gap — unattributed by the local hook |
| 14-16 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 17-28 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593350+00:00 | pre-commit gap — unattributed by the local hook |
| 29-32 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 33-49 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-24T10:59:27.955415+00:00 |  |
| 50-82 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 83-166 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.593421+00:00 | pre-commit gap — unattributed by the local hook |
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
| 230-269 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594102+00:00 | pre-commit gap — unattributed by the local hook |
| 270-270 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 271-273 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594169+00:00 | pre-commit gap — unattributed by the local hook |
| 274-276 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 277-277 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594235+00:00 | pre-commit gap — unattributed by the local hook |
| 278-279 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.306592+00:00 |  |
| 280-335 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.594307+00:00 | pre-commit gap — unattributed by the local hook |
