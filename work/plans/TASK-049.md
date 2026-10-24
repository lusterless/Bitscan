# TASK-049 plan: body caps by path template, and the after-auth mode

REQs: REQ-066 (and REQ-037, which keeps holding). Owner: impl-manager. Recommended second look. Depends on: nothing. Files: `bm/app.py`. Consumers: TASK-063 (`bm/api/agent/bodies.py`, the capped reader), TASK-073 (results), TASK-074 (inventory). Tests: TP-M3-03.

## Why (M2 gate review carry-over)

`BodyLimit` looks up `scope["path"]` exactly in `route_caps` (`app.py` L111). Agent routes are templated (`/api/v1/agent/{id}/inventory`), so a concrete path never matches and every agent route would get the 1 MiB JSON cap: valid inventory uploads (up to 10 MiB gzip, TS §6.3 L1138) would be refused. Second, `BodyLimit` answers 413 itself, before the app and its token check run, so an oversized inventory upload is never audit-logged and its job never fails, although TS §3.4 L240 says "Anything over a limit is rejected (413 or 422) and audit-logged" and L244 that a 413-rejected upload's job "becomes `failed`".

## Spec quotes

- TS §6.3 L1138: "Size limits: inventory upload 10 MB gzip / 64 MB decompressed; result batch 1.5 MB after decompression; `.bit` 5 MB; other JSON bodies 1 MB. Larger bodies get 413."
- TS §6.1 L1072: "The manager re-checks every size cap itself (§3.4, §4.5); it never trusts the agent's own limits."
- TS §8.1 L1250: "Streaming decompression with hard caps on bytes, rows and field lengths; server-side output caps; request size limits."

## Interface

```python
# bm/app.py
@dataclass(frozen=True)
class RouteCap:
    template: str            # e.g. "/api/v1/agent/{id}/inventory", FastAPI path syntax
    cap_class: str           # "inventory" | "result_batch" | "bit" | "json"
    limit: int               # bytes, <= BODY_CAP_CLASSES[cap_class]
    after_auth: bool = False # the route enforces the cap itself, after its token check

ROUTE_BODY_CAPS: list[RouteCap] = []   # replaces the (path, class, bytes) tuples; registered by route modules

class CappedReceive:  # wraps receive(); raises BodyTooLarge once more than limit bytes arrived
    ...
BODY_CAP_SCOPE_KEY: Final = "bitscan.body_cap"   # scope entry the route reads: limit and the Content-Length seen
```

- Templates are compiled once at app creation with Starlette's `compile_path`, and matched in registration order; two caps for one template, an unknown class or a limit above the class maximum raise `ValueError` at app creation (REQ-037 (5)).
- **Normal mode** (every cap without `after_auth`, and the 1 MiB default): unchanged M2 behaviour (Content-Length pre-check, buffered read up to cap + 1, 413 `too_large` from the middleware).
- **After-auth mode**: the middleware does not answer 413 and does not buffer. It passes the request on with `receive` wrapped by `CappedReceive(limit)` and puts `{limit, content_length}` in the scope. The route's dependencies (token check) run first, because the handler declares no body parameter; then `bodies.read_capped(request)` (TASK-063) answers 413 if `Content-Length` exceeds the limit (without reading) or if the stream passes the limit (after reading at most limit + 1 bytes), so the route can audit and fail the job before answering. The app can never read more than limit + 1 bytes, because `CappedReceive` raises past it.

## Edge cases

- A client that sends `Content-Length: 5` and then more bytes: `CappedReceive` counts real bytes, not the header.
- A request whose token check fails never has its body read in after-auth mode; uvicorn drains or closes the connection. The 401 answer is the same as for any agent route (REQ-066 (3)).
- Decompressed caps (64 MiB inventory, 1.5 MiB results) are not this task: they belong to `gunzip_capped` (TASK-060), used by TASK-073 and TASK-074.
- User routes register nothing, so they keep the 1 MiB default (REQ-066 (6)).
- The `.bit` 5 MiB cap (M7) will use normal mode with a template; nothing changes for it.
