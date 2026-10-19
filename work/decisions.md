# Decisions (lead)

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-19 | For the workspace clean-up, `implementer` is the single writer of `.claude/**`, `README.md`, `.gitignore`, `.gitattributes` and `docs/agent-teams-reference.md`. | The user asked for these documents to be fixed; round 1 showed the implementer declines such edits without authorisation, and one writer avoids conflicting edits. This is an exception to the `manager/`, `agent/`, `web/`, `bits/samples/`, `deploy/` ownership in CLAUDE.md, limited to this task. |
| 2026-10-19 | Spec-silent or inferred behaviour is written into the rules only as an `**Open spec question:**` line, never as a rule. Workflow choices go to the user as DECIDE items. | `.claude/CLAUDE.md`: "If code and spec disagree, or the spec is silent, stop and ask; do not guess." |
| 2026-10-19 | No commit is made in this task. | The user has not asked for one. |
