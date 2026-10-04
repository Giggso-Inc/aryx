# Attribution — src/aryx/pipeline/doc_discovery/doc_discovery.py

Last updated: 2026-10-04T15:42:14.647187+00:00
Total lines: 1036
Lines AI-generated: 158 (15.3%)
Lines human-typed: 216
Lines joint: 0
Lines unattributed: 662
Owner (most recent author): m.munir@giggso.com

| Line Range | Human Author | AI Model | Mode | Skill | Signed By | Commit | Date (UTC) | Reason |
| ---------- | ------------ | -------- | ---- | ----- | --------- | ------ | ---------- | ------ |
| 1-24 | m.munir@giggso.com | — | — | — | — | — | 2026-09-23T13:50:04.192098+00:00 | pre-commit gap — unattributed by the local hook |
| 25-29 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T13:20:43.880838+00:00 |  |
| 30-40 | m.munir@giggso.com | — | — | — | — | — | 2026-09-30T11:16:45.256423+00:00 | pre-commit gap — unattributed by the local hook |
| 41-42 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-30T10:55:44.076555+00:00 |  |
| 43-52 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:09:36.119034+00:00 | pre-commit gap — unattributed by the local hook |
| 53-53 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:57:05.598775+00:00 |  |
| 54-57 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:41:09.853327+00:00 |  |
| 58-84 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:47:48.085318+00:00 | pre-commit gap — unattributed by the local hook |
| 85-87 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942288+00:00 | pre-commit gap — unattributed by the local hook |
| 88-89 | m.munir@giggso.com | — | — | — | — | — | 2026-09-30T12:35:49.179426+00:00 |  |
| 90-91 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T15:46:59.445253+00:00 | pre-commit gap — unattributed by the local hook |
| 92-93 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T11:51:46.837065+00:00 |  |
| 94-100 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T15:46:59.445318+00:00 | pre-commit gap — unattributed by the local hook |
| 101-106 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T16:44:21.126905+00:00 |  |
| 107-107 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513514+00:00 | pre-commit gap — unattributed by the local hook |
| 108-111 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T03:24:53.718072+00:00 | pre-commit gap — unattributed by the local hook |
| 112-114 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513588+00:00 | pre-commit gap — unattributed by the local hook |
| 115-120 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:48:16.912162+00:00 |  |
| 121-124 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.349738+00:00 |  |
| 125-136 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513666+00:00 | pre-commit gap — unattributed by the local hook |
| 137-141 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 142-148 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513745+00:00 | pre-commit gap — unattributed by the local hook |
| 149-157 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.349738+00:00 |  |
| 158-161 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513822+00:00 | pre-commit gap — unattributed by the local hook |
| 162-163 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T03:24:53.718287+00:00 | pre-commit gap — unattributed by the local hook |
| 164-164 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T11:51:46.837065+00:00 |  |
| 165-165 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T03:24:53.718414+00:00 | pre-commit gap — unattributed by the local hook |
| 166-167 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942331+00:00 | pre-commit gap — unattributed by the local hook |
| 168-168 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513899+00:00 | pre-commit gap — unattributed by the local hook |
| 169-195 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.349738+00:00 |  |
| 196-197 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T04:48:24.495774+00:00 |  |
| 198-211 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.349738+00:00 |  |
| 212-215 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.513976+00:00 | pre-commit gap — unattributed by the local hook |
| 216-224 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T15:46:59.445393+00:00 | pre-commit gap — unattributed by the local hook |
| 225-227 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 228-232 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-03T14:57:22.289927+00:00 |  |
| 233-236 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T15:46:59.445457+00:00 | pre-commit gap — unattributed by the local hook |
| 237-237 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.666835+00:00 |  |
| 238-257 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514064+00:00 | pre-commit gap — unattributed by the local hook |
| 258-259 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T08:46:38.349738+00:00 |  |
| 260-261 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514142+00:00 | pre-commit gap — unattributed by the local hook |
| 262-262 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:41:27.530485+00:00 |  |
| 263-266 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584013+00:00 | pre-commit gap — unattributed by the local hook |
| 267-267 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:41:27.530485+00:00 |  |
| 268-271 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584055+00:00 | pre-commit gap — unattributed by the local hook |
| 272-274 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 275-279 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:40:44.606048+00:00 |  |
| 280-280 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.666835+00:00 |  |
| 281-303 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T14:47:48.085580+00:00 | pre-commit gap — unattributed by the local hook |
| 304-307 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-23T13:22:15.080643+00:00 |  |
| 308-308 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 309-312 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514219+00:00 | pre-commit gap — unattributed by the local hook |
| 313-326 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T05:17:12.984850+00:00 |  |
| 327-327 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514297+00:00 | pre-commit gap — unattributed by the local hook |
| 328-335 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584139+00:00 | pre-commit gap — unattributed by the local hook |
| 336-341 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 342-355 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584181+00:00 | pre-commit gap — unattributed by the local hook |
| 356-359 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 360-375 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584223+00:00 | pre-commit gap — unattributed by the local hook |
| 376-376 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 377-380 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584265+00:00 | pre-commit gap — unattributed by the local hook |
| 381-388 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 389-392 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584307+00:00 | pre-commit gap — unattributed by the local hook |
| 393-399 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 400-411 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584349+00:00 | pre-commit gap — unattributed by the local hook |
| 412-415 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 416-430 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584391+00:00 | pre-commit gap — unattributed by the local hook |
| 431-431 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 432-435 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584433+00:00 | pre-commit gap — unattributed by the local hook |
| 436-442 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 443-445 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584474+00:00 | pre-commit gap — unattributed by the local hook |
| 446-448 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 449-464 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584520+00:00 | pre-commit gap — unattributed by the local hook |
| 465-469 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 470-485 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584563+00:00 | pre-commit gap — unattributed by the local hook |
| 486-500 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-09-25T13:33:41.088471+00:00 |  |
| 501-504 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584605+00:00 | pre-commit gap — unattributed by the local hook |
| 505-505 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T15:41:27.530485+00:00 |  |
| 506-514 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584648+00:00 | pre-commit gap — unattributed by the local hook |
| 515-518 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 519-522 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T05:56:43.534791+00:00 | pre-commit gap — unattributed by the local hook |
| 523-550 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T15:32:14.255041+00:00 |  |
| 551-556 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:49:12.054595+00:00 |  |
| 557-566 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T12:14:05.205091+00:00 |  |
| 567-570 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584829+00:00 | pre-commit gap — unattributed by the local hook |
| 571-571 | m.munir@giggso.com | — | — | — | — | — | 2026-10-02T17:58:51.666835+00:00 |  |
| 572-585 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584872+00:00 | pre-commit gap — unattributed by the local hook |
| 586-601 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-04T15:32:21.238871+00:00 |  |
| 602-605 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584872+00:00 | pre-commit gap — unattributed by the local hook |
| 606-640 | m.munir@giggso.com | claude-sonnet-5 | auto | — | — | — | 2026-10-02T14:57:22.403376+00:00 |  |
| 641-643 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584914+00:00 | pre-commit gap — unattributed by the local hook |
| 644-652 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 653-698 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.584966+00:00 | pre-commit gap — unattributed by the local hook |
| 699-702 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 703-728 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585023+00:00 | pre-commit gap — unattributed by the local hook |
| 729-732 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 733-733 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585085+00:00 | pre-commit gap — unattributed by the local hook |
| 734-734 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 735-755 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585135+00:00 | pre-commit gap — unattributed by the local hook |
| 756-761 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 762-763 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585179+00:00 | pre-commit gap — unattributed by the local hook |
| 764-764 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 765-767 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585222+00:00 | pre-commit gap — unattributed by the local hook |
| 768-770 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 771-775 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585264+00:00 | pre-commit gap — unattributed by the local hook |
| 776-783 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 784-784 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585307+00:00 | pre-commit gap — unattributed by the local hook |
| 785-789 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 790-807 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585349+00:00 | pre-commit gap — unattributed by the local hook |
| 808-809 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 810-810 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585392+00:00 | pre-commit gap — unattributed by the local hook |
| 811-822 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 823-825 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585435+00:00 | pre-commit gap — unattributed by the local hook |
| 826-835 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 836-870 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585478+00:00 | pre-commit gap — unattributed by the local hook |
| 871-872 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 873-875 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585520+00:00 | pre-commit gap — unattributed by the local hook |
| 876-881 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 882-910 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585563+00:00 | pre-commit gap — unattributed by the local hook |
| 911-912 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 913-918 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:58:03.585606+00:00 | pre-commit gap — unattributed by the local hook |
| 919-924 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T08:56:52.169499+00:00 |  |
| 925-936 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T10:27:57.942376+00:00 | pre-commit gap — unattributed by the local hook |
| 937-957 | m.munir@giggso.com | — | — | — | — | — | 2026-10-03T15:46:59.445514+00:00 | pre-commit gap — unattributed by the local hook |
| 958-982 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T03:24:53.718521+00:00 | pre-commit gap — unattributed by the local hook |
| 983-989 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T05:56:43.534866+00:00 | pre-commit gap — unattributed by the local hook |
| 990-1003 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T10:53:44.514380+00:00 | pre-commit gap — unattributed by the local hook |
| 1004-1005 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T13:52:27.855221+00:00 | pre-commit gap — unattributed by the local hook |
| 1006-1036 | m.munir@giggso.com | — | — | — | — | — | 2026-10-04T15:42:14.460147+00:00 | pre-commit gap — unattributed by the local hook |
