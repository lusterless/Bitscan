# TASK-113 TEST: GET /api/v1/packages/search

Verdict: **PASS**. REQ-113 (2)-(4), REQ-114 through the API, REQ-115 (1), (2), (4)-(6). Commands: W run m5-t113a, tests/test_package_search_pg.py; re-run 7/7 of test_injection_text_is_literal_through_the_api (test bug: `%s` is a 2-char q). Plants CHK-M5-328, 330 (route), 335, 352, 353 (route): all red.

AC: refusals 400 problem naming the parameter, no value echoed CHK-M5-120; limits CHK-M5-121; shapes and oracle sets CHK-M5-122; paging CHK-M5-123; cursor scope, tamper, anchor gone CHK-M5-124; empty CHK-M5-125; token groups CHK-M5-126; verbatim CHK-M5-127; read-only CHK-M5-128; 601st -> 429 CHK-M5-129; literal wildcards, invalid version and NUL never 500 CHK-M5-130..132; document CHK-M5-133; route walk CHK-M5-134.
