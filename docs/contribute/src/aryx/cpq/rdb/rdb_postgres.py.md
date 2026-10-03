# Attribution — src/aryx/cpq/rdb/rdb_postgres.py

Last updated: 2026-10-03T09:08:41.897325+00:00
Total lines: 645
Lines AI-generated: 43 (6.7%)
Lines human-typed: 73
Lines joint: 0
Lines unattributed: 529
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-8 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576329+00:00 | pre-commit gap — unattributed by the local hook |
| 9-9 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 10-10 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 11-14 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576370+00:00 | pre-commit gap — unattributed by the local hook |
| 15-15 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 16-16 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 17-22 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576413+00:00 | pre-commit gap — unattributed by the local hook |
| 23-34 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 35-77 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576460+00:00 | pre-commit gap — unattributed by the local hook |
| 78-79 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 80-94 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576515+00:00 | pre-commit gap — unattributed by the local hook |
| 95-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 96-109 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576558+00:00 | pre-commit gap — unattributed by the local hook |
| 110-152 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T11:57:53.719258+00:00 |  |
| 153-159 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576601+00:00 | pre-commit gap — unattributed by the local hook |
| 160-160 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 161-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576642+00:00 | pre-commit gap — unattributed by the local hook |
| 169-170 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 171-171 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576697+00:00 | pre-commit gap — unattributed by the local hook |
| 172-175 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 176-177 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 178-195 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576745+00:00 | pre-commit gap — unattributed by the local hook |
| 196-196 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 197-198 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576788+00:00 | pre-commit gap — unattributed by the local hook |
| 199-199 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 200-201 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 202-207 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576830+00:00 | pre-commit gap — unattributed by the local hook |
| 208-208 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 209-215 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576872+00:00 | pre-commit gap — unattributed by the local hook |
| 216-220 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 221-221 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 222-226 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576914+00:00 | pre-commit gap — unattributed by the local hook |
| 227-228 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 229-229 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576955+00:00 | pre-commit gap — unattributed by the local hook |
| 230-232 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 233-253 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.576997+00:00 | pre-commit gap — unattributed by the local hook |
| 254-254 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 255-256 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577039+00:00 | pre-commit gap — unattributed by the local hook |
| 257-257 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 258-258 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577081+00:00 | pre-commit gap — unattributed by the local hook |
| 259-260 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 261-266 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577124+00:00 | pre-commit gap — unattributed by the local hook |
| 267-267 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 268-274 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577166+00:00 | pre-commit gap — unattributed by the local hook |
| 275-279 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.551553+00:00 |  |
| 280-280 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577210+00:00 | pre-commit gap — unattributed by the local hook |
| 281-281 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 282-318 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577257+00:00 | pre-commit gap — unattributed by the local hook |
| 319-320 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 321-341 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577300+00:00 | pre-commit gap — unattributed by the local hook |
| 342-342 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 343-359 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577341+00:00 | pre-commit gap — unattributed by the local hook |
| 360-361 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 362-383 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577383+00:00 | pre-commit gap — unattributed by the local hook |
| 384-384 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 385-405 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577424+00:00 | pre-commit gap — unattributed by the local hook |
| 406-407 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 408-430 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577466+00:00 | pre-commit gap — unattributed by the local hook |
| 431-431 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 432-440 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577507+00:00 | pre-commit gap — unattributed by the local hook |
| 441-442 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 443-466 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577550+00:00 | pre-commit gap — unattributed by the local hook |
| 467-467 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 468-474 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577593+00:00 | pre-commit gap — unattributed by the local hook |
| 475-476 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 477-501 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577648+00:00 | pre-commit gap — unattributed by the local hook |
| 502-502 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 503-594 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577701+00:00 | pre-commit gap — unattributed by the local hook |
| 595-596 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:26.034753+00:00 |  |
| 597-622 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577745+00:00 | pre-commit gap — unattributed by the local hook |
| 623-623 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.042864+00:00 |  |
| 624-645 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.577787+00:00 | pre-commit gap — unattributed by the local hook |
