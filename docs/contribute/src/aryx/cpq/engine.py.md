# Attribution — src/aryx/cpq/engine.py

Last updated: 2026-10-06T03:40:55.888597+00:00
Total lines: 2475
Lines AI-generated: 312 (12.6%)
Lines human-typed: 65
Lines joint: 0
Lines unattributed: 2098
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-20 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569472+00:00 | pre-commit gap — unattributed by the local hook |
| 21-31 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T03:33:56.496035+00:00 |  |
| 32-36 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569514+00:00 | pre-commit gap — unattributed by the local hook |
| 37-38 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:08:53.718549+00:00 |  |
| 39-50 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569556+00:00 | pre-commit gap — unattributed by the local hook |
| 51-51 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T07:56:30.565710+00:00 |  |
| 52-316 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569611+00:00 | pre-commit gap — unattributed by the local hook |
| 317-336 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T10:46:08.573307+00:00 |  |
| 337-599 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569677+00:00 | pre-commit gap — unattributed by the local hook |
| 600-600 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.012820+00:00 |  |
| 601-700 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569758+00:00 | pre-commit gap — unattributed by the local hook |
| 701-713 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:14:04.545745+00:00 |  |
| 714-869 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569828+00:00 | pre-commit gap — unattributed by the local hook |
| 870-875 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 876-910 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569902+00:00 | pre-commit gap — unattributed by the local hook |
| 911-918 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-06T03:34:35.985171+00:00 |  |
| 919-1088 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569902+00:00 | pre-commit gap — unattributed by the local hook |
| 1089-1091 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1092-1094 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.569973+00:00 | pre-commit gap — unattributed by the local hook |
| 1095-1095 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1096-1113 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570042+00:00 | pre-commit gap — unattributed by the local hook |
| 1114-1116 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1117-1117 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570111+00:00 | pre-commit gap — unattributed by the local hook |
| 1118-1121 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T04:16:32.200309+00:00 |  |
| 1122-1149 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329554+00:00 | pre-commit gap — unattributed by the local hook |
| 1150-1164 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:10:04.175398+00:00 |  |
| 1165-1246 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570180+00:00 | pre-commit gap — unattributed by the local hook |
| 1247-1247 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1248-1253 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570251+00:00 | pre-commit gap — unattributed by the local hook |
| 1254-1255 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.012820+00:00 |  |
| 1256-1256 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570320+00:00 | pre-commit gap — unattributed by the local hook |
| 1257-1258 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.012820+00:00 |  |
| 1259-1270 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570388+00:00 | pre-commit gap — unattributed by the local hook |
| 1271-1271 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1272-1274 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570458+00:00 | pre-commit gap — unattributed by the local hook |
| 1275-1277 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.012820+00:00 |  |
| 1278-1341 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570528+00:00 | pre-commit gap — unattributed by the local hook |
| 1342-1345 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 1346-1351 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570598+00:00 | pre-commit gap — unattributed by the local hook |
| 1352-1352 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1353-1356 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570667+00:00 | pre-commit gap — unattributed by the local hook |
| 1357-1357 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.501961+00:00 |  |
| 1358-1371 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570747+00:00 | pre-commit gap — unattributed by the local hook |
| 1372-1383 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:13:49.007091+00:00 |  |
| 1384-1409 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570823+00:00 | pre-commit gap — unattributed by the local hook |
| 1410-1410 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 1411-1415 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570893+00:00 | pre-commit gap — unattributed by the local hook |
| 1416-1416 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 1417-1454 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.570963+00:00 | pre-commit gap — unattributed by the local hook |
| 1455-1490 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T05:45:05.572270+00:00 |  |
| 1491-1596 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329718+00:00 | pre-commit gap — unattributed by the local hook |
| 1597-1609 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:15:05.126273+00:00 |  |
| 1610-1657 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329767+00:00 | pre-commit gap — unattributed by the local hook |
| 1658-1702 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-21T10:25:31.522974+00:00 |  |
| 1703-1729 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.571031+00:00 | pre-commit gap — unattributed by the local hook |
| 1730-1748 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 1749-1757 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.571099+00:00 | pre-commit gap — unattributed by the local hook |
| 1758-1758 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 1759-1760 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.571169+00:00 | pre-commit gap — unattributed by the local hook |
| 1761-1774 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T06:35:25.989356+00:00 |  |
| 1775-2124 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.571239+00:00 | pre-commit gap — unattributed by the local hook |
| 2125-2139 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:29:47.430235+00:00 |  |
| 2140-2151 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329861+00:00 | pre-commit gap — unattributed by the local hook |
| 2152-2163 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:29:50.796461+00:00 |  |
| 2164-2257 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329909+00:00 | pre-commit gap — unattributed by the local hook |
| 2258-2288 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:28.690509+00:00 |  |
| 2289-2301 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.329970+00:00 | pre-commit gap — unattributed by the local hook |
| 2302-2331 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:34.309982+00:00 |  |
| 2332-2337 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.330016+00:00 | pre-commit gap — unattributed by the local hook |
| 2338-2368 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:45.227943+00:00 |  |
| 2369-2375 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T09:55:00.330062+00:00 | pre-commit gap — unattributed by the local hook |
| 2376-2388 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-29T08:31:52.810810+00:00 |  |
| 2389-2401 | m.munir@giggso.com | — | — | — | — | — | 2026-09-29T11:26:48.815160+00:00 | pre-commit gap — unattributed by the local hook |
| 2402-2459 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.571308+00:00 | pre-commit gap — unattributed by the local hook |
| 2460-2475 | m.munir@giggso.com | — | — | — | — | — | 2026-10-06T03:40:55.690708+00:00 | pre-commit gap — unattributed by the local hook |
