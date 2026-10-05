# Attribution — src/aryx/resolution/run.py

Last updated: 2026-10-05T06:44:04.173380+00:00
Total lines: 471
Lines AI-generated: 132 (28.0%)
Lines human-typed: 70
Lines joint: 0
Lines unattributed: 269
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-27 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T14:15:46.850944+00:00 | pre-commit gap — unattributed by the local hook |
| 28-29 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.792166+00:00 | pre-commit gap — unattributed by the local hook |
| 30-32 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T06:21:28.704038+00:00 |  |
| 33-36 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.589953+00:00 | pre-commit gap — unattributed by the local hook |
| 37-38 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 39-50 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.792318+00:00 | pre-commit gap — unattributed by the local hook |
| 51-66 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:44:03.973395+00:00 | pre-commit gap — unattributed by the local hook |
| 67-85 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T06:40:50.791854+00:00 |  |
| 86-86 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:44:03.973498+00:00 | pre-commit gap — unattributed by the local hook |
| 87-95 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T04:53:05.487877+00:00 |  |
| 96-96 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.074240+00:00 |  |
| 97-97 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.792697+00:00 | pre-commit gap — unattributed by the local hook |
| 98-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.867735+00:00 |  |
| 101-103 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.792822+00:00 | pre-commit gap — unattributed by the local hook |
| 104-104 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.867735+00:00 |  |
| 105-107 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.792947+00:00 | pre-commit gap — unattributed by the local hook |
| 108-108 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.867735+00:00 |  |
| 109-111 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.074240+00:00 |  |
| 112-112 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:01:39.533851+00:00 | pre-commit gap — unattributed by the local hook |
| 113-114 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.516203+00:00 | pre-commit gap — unattributed by the local hook |
| 115-116 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793031+00:00 | pre-commit gap — unattributed by the local hook |
| 117-119 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T05:31:33.867735+00:00 |  |
| 120-124 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793132+00:00 | pre-commit gap — unattributed by the local hook |
| 125-125 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590302+00:00 | pre-commit gap — unattributed by the local hook |
| 126-126 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 127-139 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590368+00:00 | pre-commit gap — unattributed by the local hook |
| 140-141 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 142-149 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590435+00:00 | pre-commit gap — unattributed by the local hook |
| 150-156 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 157-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590507+00:00 | pre-commit gap — unattributed by the local hook |
| 169-169 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 170-174 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590575+00:00 | pre-commit gap — unattributed by the local hook |
| 175-175 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 176-178 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590642+00:00 | pre-commit gap — unattributed by the local hook |
| 179-179 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 180-182 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590719+00:00 | pre-commit gap — unattributed by the local hook |
| 183-183 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 184-219 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590788+00:00 | pre-commit gap — unattributed by the local hook |
| 220-263 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T14:05:21.850014+00:00 |  |
| 264-268 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793240+00:00 | pre-commit gap — unattributed by the local hook |
| 269-276 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T06:22:11.391916+00:00 |  |
| 277-292 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793346+00:00 | pre-commit gap — unattributed by the local hook |
| 293-293 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 294-305 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.590925+00:00 | pre-commit gap — unattributed by the local hook |
| 306-308 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 309-312 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T06:21:53.699208+00:00 |  |
| 313-315 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793452+00:00 | pre-commit gap — unattributed by the local hook |
| 316-316 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:33:50.979269+00:00 |  |
| 317-320 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793560+00:00 | pre-commit gap — unattributed by the local hook |
| 321-325 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.248646+00:00 |  |
| 326-331 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.591072+00:00 | pre-commit gap — unattributed by the local hook |
| 332-355 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T06:40:39.244425+00:00 |  |
| 356-370 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:43:07.002625+00:00 |  |
| 371-373 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:44:03.973578+00:00 | pre-commit gap — unattributed by the local hook |
| 374-374 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:33:41.928926+00:00 |  |
| 375-378 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:44:03.973652+00:00 | pre-commit gap — unattributed by the local hook |
| 379-399 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-05T06:40:28.349120+00:00 |  |
| 400-400 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:25:57.793669+00:00 | pre-commit gap — unattributed by the local hook |
| 401-401 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:33:50.979269+00:00 |  |
| 402-413 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:44:03.973723+00:00 | pre-commit gap — unattributed by the local hook |
| 414-428 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:43:07.002625+00:00 |  |
| 429-471 | m.munir@giggso.com | — | — | — | — | — | 2026-10-05T06:44:03.973795+00:00 | pre-commit gap — unattributed by the local hook |
