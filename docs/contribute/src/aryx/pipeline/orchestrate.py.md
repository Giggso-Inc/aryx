# Attribution — src/aryx/pipeline/orchestrate.py

Last updated: 2026-10-03T09:08:41.892696+00:00
Total lines: 392
Lines AI-generated: 10 (2.6%)
Lines human-typed: 91
Lines joint: 0
Lines unattributed: 291
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-11 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587805+00:00 | pre-commit gap — unattributed by the local hook |
| 12-12 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 13-21 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587856+00:00 | pre-commit gap — unattributed by the local hook |
| 22-23 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 24-25 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587907+00:00 | pre-commit gap — unattributed by the local hook |
| 26-32 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T17:33:13.585368+00:00 |  |
| 33-46 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.119435+00:00 | pre-commit gap — unattributed by the local hook |
| 47-47 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.679842+00:00 |  |
| 48-60 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.119509+00:00 | pre-commit gap — unattributed by the local hook |
| 61-61 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.679842+00:00 |  |
| 62-65 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.119583+00:00 | pre-commit gap — unattributed by the local hook |
| 66-67 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.587958+00:00 | pre-commit gap — unattributed by the local hook |
| 68-71 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 72-72 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588014+00:00 | pre-commit gap — unattributed by the local hook |
| 73-76 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 77-93 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588065+00:00 | pre-commit gap — unattributed by the local hook |
| 94-95 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 96-97 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588114+00:00 | pre-commit gap — unattributed by the local hook |
| 98-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 105-113 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588165+00:00 | pre-commit gap — unattributed by the local hook |
| 114-118 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 119-121 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588218+00:00 | pre-commit gap — unattributed by the local hook |
| 122-148 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 149-194 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588270+00:00 | pre-commit gap — unattributed by the local hook |
| 195-201 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 202-202 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588323+00:00 | pre-commit gap — unattributed by the local hook |
| 203-208 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 209-246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588376+00:00 | pre-commit gap — unattributed by the local hook |
| 247-251 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 252-273 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588426+00:00 | pre-commit gap — unattributed by the local hook |
| 274-276 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T13:01:04.984150+00:00 |  |
| 277-281 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 282-282 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588476+00:00 | pre-commit gap — unattributed by the local hook |
| 283-293 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T17:51:30.525626+00:00 | pre-commit gap — unattributed by the local hook |
| 294-298 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T13:08:37.489247+00:00 | pre-commit gap — unattributed by the local hook |
| 299-300 | m.munir@giggso.com | — | — | — | — | — | 2026-09-30T12:35:49.187553+00:00 |  |
| 301-305 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 306-376 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588525+00:00 | pre-commit gap — unattributed by the local hook |
| 377-379 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 380-387 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588575+00:00 | pre-commit gap — unattributed by the local hook |
| 388-391 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.210081+00:00 |  |
| 392-392 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.588624+00:00 | pre-commit gap — unattributed by the local hook |
