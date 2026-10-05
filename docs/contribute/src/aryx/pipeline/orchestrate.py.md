# Attribution — src/aryx/pipeline/orchestrate.py

Last updated: 2026-10-04T10:55:53.726761+00:00
Total lines: 418
Lines AI-generated: 67 (16.0%)
Lines human-typed: 82
Lines joint: 0
Lines unattributed: 269
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-11 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587805+00:00 | pre-commit gap — unattributed by the local hook |
| 12-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 13-21 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587856+00:00 | pre-commit gap — unattributed by the local hook |
| 22-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 24-25 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587907+00:00 | pre-commit gap — unattributed by the local hook |
| 26-32 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T17:33:13.585368+00:00 |  |
| 33-44 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.119435+00:00 | pre-commit gap — unattributed by the local hook |
| 45-66 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:32:14.451466+00:00 |  |
| 67-67 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514460+00:00 | pre-commit gap — unattributed by the local hook |
| 68-71 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 72-72 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588014+00:00 | pre-commit gap — unattributed by the local hook |
| 73-74 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514517+00:00 | pre-commit gap — unattributed by the local hook |
| 75-93 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T07:32:24.255504+00:00 |  |
| 94-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 96-97 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588114+00:00 | pre-commit gap — unattributed by the local hook |
| 98-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 105-113 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588165+00:00 | pre-commit gap — unattributed by the local hook |
| 114-118 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 119-121 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588218+00:00 | pre-commit gap — unattributed by the local hook |
| 122-148 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 149-186 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514569+00:00 | pre-commit gap — unattributed by the local hook |
| 187-191 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:35:20.616236+00:00 |  |
| 192-194 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514625+00:00 | pre-commit gap — unattributed by the local hook |
| 195-201 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 202-202 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588323+00:00 | pre-commit gap — unattributed by the local hook |
| 203-205 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514681+00:00 | pre-commit gap — unattributed by the local hook |
| 206-213 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:35:30.090404+00:00 |  |
| 214-246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514733+00:00 | pre-commit gap — unattributed by the local hook |
| 247-251 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 252-254 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514782+00:00 | pre-commit gap — unattributed by the local hook |
| 255-257 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T10:35:35.031002+00:00 |  |
| 258-272 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514829+00:00 | pre-commit gap — unattributed by the local hook |
| 273-273 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 274-276 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T13:01:04.984150+00:00 |  |
| 277-281 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 282-282 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588476+00:00 | pre-commit gap — unattributed by the local hook |
| 283-283 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514877+00:00 | pre-commit gap — unattributed by the local hook |
| 284-284 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 285-293 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514924+00:00 | pre-commit gap — unattributed by the local hook |
| 294-298 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T13:08:37.489247+00:00 | pre-commit gap — unattributed by the local hook |
| 299-300 | m.munir@giggso.com | — | — | — | — | — | 2026-09-30T12:35:49.187553+00:00 |  |
| 301-305 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 306-312 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514972+00:00 | pre-commit gap — unattributed by the local hook |
| 313-313 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 314-335 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515031+00:00 | pre-commit gap — unattributed by the local hook |
| 336-336 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 337-347 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515081+00:00 | pre-commit gap — unattributed by the local hook |
| 348-348 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 349-371 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515135+00:00 | pre-commit gap — unattributed by the local hook |
| 372-372 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 373-376 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515184+00:00 | pre-commit gap — unattributed by the local hook |
| 377-379 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 380-387 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588575+00:00 | pre-commit gap — unattributed by the local hook |
| 388-389 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515231+00:00 | pre-commit gap — unattributed by the local hook |
| 390-390 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:09.883047+00:00 |  |
| 391-391 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515278+00:00 | pre-commit gap — unattributed by the local hook |
| 392-392 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588624+00:00 | pre-commit gap — unattributed by the local hook |
| 393-413 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T07:41:06.497798+00:00 | pre-commit gap — unattributed by the local hook |
| 414-418 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.515324+00:00 | pre-commit gap — unattributed by the local hook |
