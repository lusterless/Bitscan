# Agent Teams: Master Reference Guide

Source: https://code.claude.com/docs/en/agent-teams (fetched 2026-10-19). Agent teams are **experimental**; re-check the source page if behavior seems to have changed.

Purpose: a working reference for designing, prompting, and running effective agent teams in this project.

---

## 1. TL;DR

- Agent teams = multiple independent Claude Code sessions. One **lead** coordinates; **teammates** each have their own context window and can message each other directly.
- Enabled via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (set in this project's shared `.claude/settings.json`).
- Use them for **parallel, independent, well-bounded work** (research, review, debugging with competing hypotheses, separate modules). Do **not** use them for sequential work, same-file edits, or heavily dependent tasks.
- They cost significantly more tokens than a single session. Default to 3-5 teammates, 5-6 tasks per teammate.
- Teammates do **not** inherit the lead's conversation. Put everything they need in the spawn prompt.
- Each teammate must own a distinct set of files.

---

## 2. Decision guide: which tool to use?

| Situation | Use |
| :- | :- |
| Focused helper, only the result matters | **Subagent** |
| Workers need to discuss, challenge, or coordinate with each other | **Agent team** |
| Sequential steps, many dependencies | **Single session** |
| Multiple edits to the same file | **Single session** |
| You run several sessions yourself and want them to pass findings | Cross-session messaging |
| Manual parallel sessions without coordination | Git worktrees |

| | Subagents | Agent teams |
| :- | :- | :- |
| Context | Own window; result returns to caller | Own window; fully independent |
| Communication | Return result to caller (named subagents can also message each other) | Teammates message each other directly |
| Coordination | Main agent manages everything | Self-coordination plus shared task list |
| Token cost | Lower | Higher (each teammate is a separate instance) |

**Strongest use cases**
1. Research and review (different lenses on the same material)
2. New modules or features (each teammate owns a separate piece)
3. Debugging with competing hypotheses
4. Cross-layer coordination (frontend / backend / tests, one owner each)

---

## 3. Enabling and configuration

### Enable

```json
// .claude/settings.json (shared with the repo) or .claude/settings.local.json (personal, gitignored)
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Without the variable: no team is set up, no team directories written, Claude does not spawn or propose teammates.

**Side effect of enabling:** any subagent Claude *names* launches as a teammate, so teams can form without being asked. To go back to plain subagents, set the variable to `"0"` (takes effect on save, no restart needed). Higher-precedence settings (project, local, `--settings`, managed) can override a user-level `0`.

**Not available in non-interactive mode** (`-p`, Agent SDK): named subagents run as ordinary subagents.

### Display modes (`teammateMode`)

| Value | Behavior |
| :- | :- |
| `"in-process"` (default) | All teammates inside the main terminal; works anywhere |
| `"auto"` | Split panes if already in tmux or iTerm2 with `it2`; else in-process |
| `"tmux"` | Split panes; auto-detects tmux vs iTerm2 |
| `"iterm2"` | iTerm2 native panes; requires `it2` CLI and Python API enabled |

Set in `~/.claude/settings.json` (`"teammateMode": "auto"`) or per session: `claude --teammate-mode auto` (experimental flag, not in `--help`).

**Split panes are NOT supported in VS Code's integrated terminal, Windows Terminal, or Ghostty.** This project is on Windows / VS Code, so **use in-process mode**.

### In-process controls

| Key | Action |
| :- | :- |
| Up / Down | Select a teammate in the agent panel |
| Enter | Open teammate transcript and message it directly |
| Esc | Clear selection; while viewing a transcript, interrupts that teammate's turn |
| `x` (on selected teammate) | Stop that teammate |
| Ctrl+T | Toggle task list |

Panel behavior: idle rows hide 30s after the whole panel goes idle and reappear on the next turn (teammate is still running). More than 3 idle teammates collapse into an `N idle agents` row; Enter expands.

When viewing a teammate: plain text and skills go to the teammate; built-in commands go to the lead. `/compact`, `/clear`, `/rewind` ask for confirmation (they act on the lead). `/model` and `/fast` do not run from this view.

---

## 4. Architecture

| Component | Role |
| :- | :- |
| Team lead | Main session; spawns teammates, coordinates, synthesizes |
| Teammates | Separate Claude Code instances working assigned tasks |
| Task list | Shared work items; states: pending / in progress / completed; supports dependencies |
| Mailbox | JSON inbox per agent at `~/.claude/teams/{team-name}/inboxes/{agent-name}.json` |

- Team name = `session-` + first 8 chars of session ID.
- Team config: `~/.claude/teams/{team-name}/config.json`. Holds runtime state. **Never hand-edit or pre-author**; it is overwritten. Removed when the session ends.
- Task list: `~/.claude/tasks/{team-name}/`. Persists after the session; retention governed by `cleanupPeriodDays`.
- No project-level team config exists (`.claude/teams/teams.json` is just a file). Define reusable roles via **subagent definitions** instead.
- Task claiming uses file locking (no double-claims). Completing a task auto-unblocks dependents.
- A message is "sent" only if the mailbox write succeeds; otherwise the sender gets an error.
- Teammates can read the team config to discover other members.

### How Claude starts a team

Claude launches a teammate when it calls the Agent tool with a `name` while teams are enabled (unless it's a fork or passes `isolation`). No confirmation prompt. If Claude used subagents when you wanted a team, ask again and **explicitly request an agent team**.

---

## 5. Spawning teammates

### Natural-language spawn

Describe the task and the roles. Be explicit about count, roles, names, and model.

```text
I'm designing a CLI tool that helps developers track TODO comments across
their codebase. Spawn three teammates to explore this from different angles:
one on UX, one on technical architecture, one playing devil's advocate.
```

```text
Spawn 4 teammates to refactor these modules in parallel. Use Sonnet for
each teammate.
```

**Tip:** name the teammates in your instruction (e.g. "call them `security`, `perf`, `tests`") so you can reference them predictably later. Otherwise the lead picks names.

### Model selection (first match wins)

1. Model named in the spawn prompt for that teammate
2. The subagent definition's `model` (`inherit` = lead's model)
3. `CLAUDE_CODE_SUBAGENT_MODEL` (if not `inherit`)
4. Lead's current model

- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` skips 1-2 and forces #3/#4 (v2.1.257+).
- Org `availableModels` allowlist can substitute blocked models.
- `teammateDefaultModel` was **removed** (v2.1.234); name the model in the prompt.
- A teammate's model and fast mode are fixed at spawn.
- Teammates inherit the lead's effort level by default.

### Reusable roles via subagent definitions

Define a role once in `.claude/agents/` (project), user, managed, or plugin scope, then reference it:

```text
Spawn a teammate using the security-reviewer agent type to audit the auth module.
```

What gets applied from the definition:

| Field | In-process teammate | Split-pane teammate |
| :- | :- | :- |
| `tools` | Limits tools; `SendMessage` and Task tools auto-added | Limits tools |
| `model` | Used if spawn prompt names none | Same |
| `disallowedTools` | Removed (SendMessage/Task tools stay) | Not stated in docs |
| `effort` | Applied | Not stated in docs |
| `autoCompactWindow` | Applied (v2.1.296+) | Ignored |
| Body | **Appended** to default system prompt | **Replaces** default system prompt |
| `skills` | **Not applied** (loads from project/user settings) | Not applied |
| `mcpServers` | Ignored (loads from project/user settings) | Applied |

Caveat: when an in-process teammate is revived, project-level `.claude/agents/` definitions are re-applied only if you have trusted that exact folder (trusting a parent does not count).

### Plan-before-implement

Put the **lead** in plan mode first, then spawn. The teammate works read-only until its plan is ready, then sends a plan approval request. **Claude Code auto-approves it in the lead's session without the lead reviewing it.** Edits and commands still go through normal permission prompts. So plan mode here is a structuring aid, not a review gate.

---

## 6. Tasks and coordination

- Lead creates tasks; teammates work through them.
- **Lead assigns** (you tell it who gets what) or **self-claim** (teammate picks next unassigned, unblocked task).
- Pending tasks with unresolved dependencies cannot be claimed.
- Agents without the Task tools coordinate by messages only.
- If the lead creates too few tasks, ask it to split the work finer. **Target 5-6 tasks per teammate.**
- Messages are per recipient; to reach everyone, send one per teammate.
- Idle notifications go to the lead automatically and include the teammate's final answer (or the error text if the turn ended on an API error).

### Task sizing

| Size | Problem |
| :- | :- |
| Too small | Coordination overhead exceeds benefit |
| Too large | Long stretches without check-ins; risk of wasted effort |
| Just right | Self-contained unit with a clear deliverable (a function, a test file, a review) |

---

## 7. Context and communication

- Each teammate loads project context at spawn: **CLAUDE.md, MCP servers, skills**. With `--setting-sources`, teammates load from the same restricted sources.
- Teammates get the **spawn prompt only**. The lead's conversation history does **not** carry over.
- So the spawn prompt must include: scope (files/dirs), constraints, relevant facts (stack, auth approach, conventions), deliverable format, and severity/priority expectations.

Good spawn prompt pattern:

```text
Spawn a security reviewer teammate with the prompt: "Review the authentication module
at src/auth/ for security vulnerabilities. Focus on token handling, session
management, and input validation. The app uses JWT tokens stored in
httpOnly cookies. Report any issues with severity ratings."
```

### Spawn prompt checklist

- [ ] Role / lens (what this teammate is responsible for, and what it is NOT)
- [ ] Exact files or directories it owns (and which are off-limits)
- [ ] Background facts it can't infer (stack, decisions, constraints)
- [ ] Concrete deliverable and format (report, patch, test file, findings doc)
- [ ] Who to message and when (e.g. "send findings to `lead`; challenge `perf`'s conclusions")
- [ ] Definition of done / when to stop
- [ ] Model (if not the lead's)

---

## 8. Permissions and security

- Teammates start with the **lead's permission mode** (except `dontAsk`, which is not inherited). If the lead uses `--dangerously-skip-permissions`, so do all teammates.
- You can change one teammate's mode **after** spawn, but cannot set per-teammate modes **at** spawn.
- Teammate permission prompts surface in the **lead's** session. Pre-approve common operations in permission settings before spawning to cut friction.
- Messages between agents are tagged as coming from another Claude session, not from you. A teammate cannot grant consent on your behalf or relay a denied action to bypass a check.
- In auto mode, the classifier treats relayed approval claims as untrusted and reviews every inter-agent message (including shutdown/plan responses) before delivery; blocked messages never arrive.

---

## 9. Quality gates (hooks)

| Hook | Fires | Exit code 2 does |
| :- | :- | :- |
| `TeammateIdle` | Teammate about to go idle | Sends feedback, keeps teammate working |
| `TaskCreated` | Task being created | Blocks creation, sends feedback |
| `TaskCompleted` | Task being marked complete | Blocks completion, sends feedback |

Use `TaskCompleted` for "tests must pass / lint must be clean before a task counts as done" and `TeammateIdle` to stop teammates quitting early.

---

## 10. Proven team patterns

### A. Parallel code review
```text
Spawn three teammates to review PR #142:
- One focused on security implications
- One checking performance impact
- One validating test coverage
Have them each review and report findings.
```
Why it works: each reviewer applies a distinct lens, so none gravitate to one issue type. The lead synthesizes.

### B. Competing-hypotheses debugging
```text
Users report the app exits after one message instead of staying connected.
Spawn 5 agent teammates to investigate different hypotheses. Have them talk to
each other to try to disprove each other's theories, like a scientific
debate. Update the findings doc with whatever consensus emerges.
```
Why it works: adversarial structure defeats anchoring; the theory that survives challenge is more likely the real root cause.

### C. Multi-perspective design exploration
UX + architecture + devil's advocate on the same problem (see section 5).

### D. Parallel module build (apply with care)
One teammate per module, each owning a disjoint set of files, with interfaces agreed up front in the spawn prompts. Higher coordination risk than A-C.

### Recommended progression
Start with research/review/investigation (no code writing), then move to parallel implementation once comfortable with coordination.

---

## 11. Best practices (condensed)

1. **Right-size the team**: 3-5 teammates; three focused beat five scattered. Scale only when work truly parallelizes.
2. **Disjoint file ownership**: two teammates editing one file = overwrites. Assign by directory/module.
3. **Rich spawn prompts**: teammates only know what you tell them (plus CLAUDE.md/skills/MCP).
4. **Right-size tasks**: self-contained, clear deliverable, 5-6 per teammate.
5. **Make the lead wait**: if it starts implementing itself, say *"Wait for your teammates to complete their tasks before proceeding."*
6. **Monitor and steer**: check in, redirect, don't leave unattended for long.
7. **Pre-approve permissions** to avoid prompt storms in the lead session.
8. **Use hooks** for quality gates.
9. **Name teammates** in the spawn instruction for predictable addressing.
10. **Define reusable roles** as subagent definitions rather than re-describing them each time.
11. **Shut down by name** when done: *"Ask the researcher teammate to shut down."* (Teammate may approve or reject with a reason.)

---

## 12. Cost notes

- Token use scales roughly linearly with active teammates; each is a full Claude instance.
- Worth it for research, review, and new feature work; not for routine tasks.
- In-process teammate prompt cache TTL is 5 minutes by default. Set `subagentPromptCacheTtl` to `"1h"` to hold it longer (1-hour cache writes cost more).
- Use cheaper models (e.g. Sonnet) for teammates doing mechanical work by naming the model in the spawn prompt.

---

## 13. Troubleshooting

| Symptom | Fix |
| :- | :- |
| Teammates not appearing | Look in the agent panel (Up/Down + Enter); hidden idle rows reappear on next turn or when messaged by name; task may have been too simple for Claude to warrant a team; for split panes check `which tmux` / `it2` + Python API |
| Claude used subagents, not a team | Ask again and explicitly request an agent team |
| Teams forming unexpectedly | Set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` to `"0"` |
| Too many permission prompts | Pre-approve operations in permission settings |
| Teammate stopped early / errored | Open its transcript; give new instructions or spawn a replacement. A message wakes a teammate waiting on API retry |
| Lead declared done too early | Tell it to keep going |
| Lead doing work itself | "Wait for your teammates to complete their tasks before proceeding" |
| Task stuck (dependents blocked) | Verify the work is done; update status manually or have the lead nudge the teammate |
| Orphaned tmux session | `tmux ls` then `tmux kill-session -t <name>` |
| Message send failures | See the "Failed to write to a teammate's inbox" error docs (disk full / mailbox not writable) |

---

## 14. Limitations (experimental)

- **No resume for in-process teammates**: `/resume` and `/rewind` don't restore them; the lead may message teammates that no longer exist. Tell it to spawn new ones.
- **Task status can lag**: teammates sometimes don't mark tasks complete.
- **Slow shutdown**: teammates finish the current request/tool call first.
- **One team per session**; no extra named teams, no sharing across sessions.
- **No nested teams**: teammates can't spawn teammates.
- **No background subagents from in-process teammates** (`background: true` errors; `run_in_background` fails or runs foreground).
- **Lead is fixed** for the session lifetime.
- **Permission modes set at spawn** (changeable afterward per teammate).
- **Split panes** need tmux or iTerm2; unsupported in VS Code terminal, Windows Terminal, Ghostty.

---

## 15. Project-specific notes (Bitscan)

- Platform: Windows 11 + VS Code, so **in-process display mode only**.
- The agent teams flag lives in the shared `.claude/settings.json`; `.claude/settings.local.json` is gitignored and personal.
- Agent definitions in `.claude/agents/` created while a session is running may not register as agent types until the session restarts. If spawning by type fails, spawn a general-purpose agent and tell it to read `.claude/agents/<role>.md` first.
- Teammates reach the main session as `main`; put that address in every spawn prompt (two teammates could not reach a teammate called `lead`).
- Wait for an explicit `FINAL:` message from each teammate. A completion notification also fires when a teammate stops to wait for replies.
- Before spawning a team here: confirm the task passes the section 2 decision guide, list disjoint file ownership per teammate, and write full spawn prompts using the section 7 checklist.

---

## 16. Quick prompt templates

**Review team**
```text
Spawn 3 teammates named security, perf, and tests to review <target>.
Each owns one lens only. Report findings with severity ratings to the lead.
Do not edit files. Wait for all three before synthesizing.
```

**Debate/debug team**
```text
<symptom>. Spawn 4 teammates named h1..h4, each investigating a different
hypothesis (<list>). They must message each other to try to disprove the
other theories. Record the surviving theory and evidence in docs/<findings>.md.
```

**Build team**
```text
Spawn N teammates, each owning exactly these paths and no others:
- <name>: <paths> -> <deliverable>
Agreed interface: <contract>. Create 5-6 tasks per teammate. Use Sonnet for
each teammate. Wait for teammates to finish; do not implement anything yourself.
```

**Shutdown**
```text
Ask each teammate to shut down, then summarize results.
```
