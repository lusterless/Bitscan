# TASK-108 TEST: status and kind enums

Verdict: **PASS**. REQ-117 (1), (2); (3) G16 is TASK-122's. Commands: W run m5-t113a (526/528, the 2 failures were test bugs in other files, re-run 1/1 and 7/7); plant AgentItem.status -> str red (7 failed). Expected values parsed from the spec DDL (TS §5.2 L710, L763, L774). M3 suites test_agents_api_pg, test_agents_admin_api_pg, test_enrolment_requests_api_pg pass unchanged. Rows: CHK-M5-001..005, -359.
