# TASK-121 IMPL: enrolment approval screen

Owner: impl-web. REQ-125, REQ-126, REQ-132; TS §3.2 (L185, L192), §6.2 (L1114–L1115); #68. Builds on TASK-116 and TASK-117. Worktree `Bitscan-m5`.

## Files

| File | Code lines |
| --- | --- |
| `web/src/screens/EnrolmentRequests.tsx` (new) | 175 |

Nothing else changed. Props are `{}` (screen contract).

## Behaviour

- **List.** `GET /api/v1/enrollment-requests?state=pending&limit=50[&cursor=…]` by default. A "Show" select switches between Pending and Decided (`state=decided`) and resets paging to the first page. Paging uses `useCursorPages` and `Pager` (TASK-117). An empty page shows "No requests.".
- **Each request** is an `<article aria-label={hostname}>` with the hostname as its heading and a `<dl>` holding these fields:

  | Field | Shown as |
  | --- | --- |
  | Kind | "New host" for `new`, "Re-enrolment of an existing agent" for `reenrol`, any other value as text |
  | Source IP | text |
  | OS | `os_pretty_name`, or "unknown" when null |
  | Agent version | text |
  | Machine-id | text |
  | Requested | formatted time |
  | Decision | only for decided requests: `decision` by user `decided_by` at `decided_at` |

- **Matching agents** (TS §3.2 L192). When `matches` is not empty, the article holds a `<section aria-label="Matching agents">` with the warning "Warning: N existing agent(s) share this hostname or machine-id. A cloned image shares the machine-id." Below it, each match is a list item with its hostname, why it matched ("same machine-id", "same hostname", or "same hostname and machine-id", found by comparing with the request), its machine-id and its status. Every match is shown (REQ-125 (1)). `status` is shown as raw text for now; TASK-122 adds the status labels.
- **Approve / Reject** (pending requests only). Each is a `Confirm` ("Approve" or "Reject", then "Confirm"), which sends `POST /api/v1/enrollment-requests/{request_id}/approve` or `/reject` **once** and then re-reads the list. A request the server has decided drops out of the pending list on that re-read (REQ-125 (3)).
- **409** shows "This request was already decided." and re-reads the list (REQ-125 (4)).
- **Other refusals** go to `ProblemBanner`: `totp_session_required` with **Sign in again**, and no field asking for an API token; `audit_sink_unavailable` with the paused message; `forbidden` with the role message (REQ-126). List refusals have their own banner. A network failure shows "The manager is unavailable. Try again later."
- **Plain text** (REQ-125 (2), REQ-132). Hostname, match hostnames, `os_pretty_name`, machine-ids, kind and status are all React text nodes or attribute values (`aria-label`). Nothing is rendered as HTML.
- A list answer that arrives after a newer request or after unmount is ignored.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No HTML rendering, no `style=`, no `fetch`, no storage, no built keys (React keys are `request_id` and `agent_id`), no `console`.

## Notes for the tester (TP-M5-14, `src/screens/EnrolmentRequests.test.tsx`)

- On mount the screen sends `GET /api/v1/enrollment-requests?state=pending&limit=50`. After each approve or reject it sends one more list request with the same query. The test double should then leave out the decided item.
- Each article has the request's hostname as its accessible name. Its "Approve" and "Reject" buttons open a Confirm alertdialog, whose "Confirm" button sends the POST.
- The `kind` and `status` fields are still plain strings in `schema.d.ts` until TASK-108/TASK-122 regenerate it. The screen does not depend on the enum.

## Revision 1 (reviewer nit in `work/reviews/TASK-121.md`, also tester-m5's observation)

- `web/src/screens/EnrolmentRequests.tsx`: the match status now renders through `StatusBadge` (TASK-122), so each match line ends `status Online` (or `Awaiting approval`, `Enrolled`, `Stale`, `Offline`, `Decommissioned`) instead of the raw enum text. It adds one import and changes one JSX line. Nothing else changed.
- **Test impact:** the existing assertion in `EnrolmentRequests.test.tsx` (about L278) expects `", status online"` and `", status decommissioned"`. It must now expect `", status Online"` and `", status Decommissioned"`. The badge is a `<span>`, so the `<li>` `textContent` is otherwise unchanged.
- `npm run typecheck`, `npm run lint` and `npm run build` pass. `npm run format:check` passes for every product file. Its only warning is the tester's `src/screens/HostDetail.test.tsx`.
