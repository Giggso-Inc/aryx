# Attribution — src/aryx/cpq/rdb/rdb_oracle.py

Last updated: 2026-10-03T09:08:41.888292+00:00
Total lines: 406
Lines AI-generated: 25 (6.2%)
Lines human-typed: 73
Lines joint: 0
Lines unattributed: 308
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-8 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.574560+00:00 | pre-commit gap — unattributed by the local hook |
| 9-9 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 10-10 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 11-14 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.574636+00:00 | pre-commit gap — unattributed by the local hook |
| 15-16 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 17-17 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 18-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.574715+00:00 | pre-commit gap — unattributed by the local hook |
| 24-34 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 35-63 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.574787+00:00 | pre-commit gap — unattributed by the local hook |
| 64-65 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 66-79 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.574858+00:00 | pre-commit gap — unattributed by the local hook |
| 80-80 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 81-87 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.574929+00:00 | pre-commit gap — unattributed by the local hook |
| 88-89 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 90-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575001+00:00 | pre-commit gap — unattributed by the local hook |
| 96-120 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T11:58:00.370933+00:00 |  |
| 121-124 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575085+00:00 | pre-commit gap — unattributed by the local hook |
| 125-125 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 126-131 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575154+00:00 | pre-commit gap — unattributed by the local hook |
| 132-133 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 134-136 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575224+00:00 | pre-commit gap — unattributed by the local hook |
| 137-140 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 141-144 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575294+00:00 | pre-commit gap — unattributed by the local hook |
| 145-146 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 147-147 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575361+00:00 | pre-commit gap — unattributed by the local hook |
| 148-149 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 150-150 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575413+00:00 | pre-commit gap — unattributed by the local hook |
| 151-151 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 152-154 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575459+00:00 | pre-commit gap — unattributed by the local hook |
| 155-155 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 156-162 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575506+00:00 | pre-commit gap — unattributed by the local hook |
| 163-167 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 168-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 169-173 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575550+00:00 | pre-commit gap — unattributed by the local hook |
| 174-177 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 178-181 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575592+00:00 | pre-commit gap — unattributed by the local hook |
| 182-183 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 184-185 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575634+00:00 | pre-commit gap — unattributed by the local hook |
| 186-187 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 188-192 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575676+00:00 | pre-commit gap — unattributed by the local hook |
| 193-193 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 194-201 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575730+00:00 | pre-commit gap — unattributed by the local hook |
| 202-206 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.541665+00:00 |  |
| 207-207 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 208-225 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575773+00:00 | pre-commit gap — unattributed by the local hook |
| 226-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 228-247 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575815+00:00 | pre-commit gap — unattributed by the local hook |
| 248-248 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 249-257 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575858+00:00 | pre-commit gap — unattributed by the local hook |
| 258-259 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 260-280 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575901+00:00 | pre-commit gap — unattributed by the local hook |
| 281-281 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 282-293 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575943+00:00 | pre-commit gap — unattributed by the local hook |
| 294-295 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 296-317 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.575985+00:00 | pre-commit gap — unattributed by the local hook |
| 318-318 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 319-321 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576027+00:00 | pre-commit gap — unattributed by the local hook |
| 322-323 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 324-346 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576069+00:00 | pre-commit gap — unattributed by the local hook |
| 347-347 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 348-349 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576114+00:00 | pre-commit gap — unattributed by the local hook |
| 350-351 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 352-375 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576157+00:00 | pre-commit gap — unattributed by the local hook |
| 376-376 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 377-377 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576199+00:00 | pre-commit gap — unattributed by the local hook |
| 378-379 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.022470+00:00 |  |
| 380-404 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576242+00:00 | pre-commit gap — unattributed by the local hook |
| 405-405 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.038122+00:00 |  |
| 406-406 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576286+00:00 | pre-commit gap — unattributed by the local hook |
