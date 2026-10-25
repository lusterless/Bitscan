# TASK-117 IMPL: shared display components

Owner: impl-web. REQ-126, REQ-127, REQ-132. Builds on TASK-116 (`problems.ts`, `router.ts`, `session.ts`). Worktree `Bitscan-m5`.

## Files (all new; nothing else changed)

| File | Code lines | What |
| --- | --- | --- |
| `web/src/components/Pager.tsx` | 59 | `useCursorPages()` hook and `Pager` component |
| `web/src/components/ProblemBanner.tsx` | 31 | `ProblemBanner` |
| `web/src/components/Confirm.tsx` | 53 | `Confirm` |
| `web/src/format.ts` | 26 | `formatTime` |

## Interfaces (for the screens and the tests)

```ts
// Pager.tsx
interface CursorPages {
  readonly cursor: string | null;      // cursor to request the current page with; null = first page
  readonly hasPrevious: boolean;
  readonly next: (cursor: string) => void;
  readonly previous: () => void;
  readonly reset: () => void;           // back to the first page (for example after the filters change)
}
function useCursorPages(): CursorPages;
function Pager(props: { pages: CursorPages; nextCursor: string | null; disabled?: boolean }): JSX.Element;

// ProblemBanner.tsx
function ProblemBanner(props: { problem: ProblemInfo | null }): JSX.Element | null;

// Confirm.tsx
function Confirm(props: {
  label: string; message: string; confirmLabel?: string /* "Confirm" */;
  onConfirm: () => void; disabled?: boolean;
}): JSX.Element;

// format.ts
function formatTime(value: string | null): string;
```

## Behaviour

- **Pager.** The API returns only `next_cursor`, so `useCursorPages` keeps a stack of the cursors of the pages opened after the first. `cursor` is the top of the stack (null on the first page). **Next** pushes the current page's `next_cursor` and is disabled when it is null. **Previous** pops and is disabled on the first page. The screen fetches with `pages.cursor` and passes the answer's `next_cursor` to `Pager`. Walking N + 1 items with page size N looks like this: the first page has N items with `next_cursor` c1; Next requests `cursor=c1` and shows 1 item with `next_cursor` null (Next disabled); Previous requests the first page again (`cursor` absent) with Previous disabled. Buttons are inside `<nav aria-label="Pages">` and labelled "Previous" and "Next".
- **ProblemBanner.** Renders nothing for `null`. Otherwise it renders `role="alert"`, then the `messageFor()` text (TASK-116, fixed words), then `detail` as its own text node when it is not null. The action is a **"Sign in again"** button that calls `signOut()` (`totp_session_required`, #85 (b)), or a **"Set up TOTP"** link to `#/account/totp` (`totp_enrolment_required`). No action asks for or accepts an API token (CHK-M5-347). There is no HTML rendering anywhere, so a hostile `detail` shows literally.
- **Confirm.** A first click on the `label` button only opens an inline `role="alertdialog"` (accessible name = `label`) holding `message` as text, a confirm button (`confirmLabel`, default "Confirm") and "Cancel". `onConfirm` is called once, on the confirm button only. Cancel closes it without calling anything. `disabled` disables both the opening button and the confirm button. It does not use `window.confirm` or a portal.
- **formatTime.** `null` gives `"never"`. A parsable RFC 3339 value is shown in UTC as `YYYY-MM-DD HH:MM:SS UTC` (for example `2026-10-24T12:03:04Z` gives `2026-10-24 12:03:04 UTC`). A value that does not parse is returned unchanged (still rendered as text). **Display choice (spec silent):** UTC rather than the browser's local zone, to match the API's RFC 3339 UTC timestamps (TS §6.3) and the audit log. The reviewer can change this.

## Checks run (Windows, Node 24.22.0)

- `npm run typecheck`, `npm run lint`, `npm run format:check`: pass.
- No `style=` attributes, no `dangerouslySetInnerHTML`, no `fetch`, no storage, no built keys.

## Notes for the tester (TP-M5-10, `src/components/components.test.tsx`)

- A pager harness needs a small test component that calls `useCursorPages()`, requests with `pages.cursor`, and renders `<Pager pages={pages} nextCursor={answer.next_cursor} />`.
- Importing `ProblemBanner` imports `session.ts`, which registers the middleware on `api` (stub `fetch` first). "Sign in again" calls `POST /api/v1/auth/logout` through it.
