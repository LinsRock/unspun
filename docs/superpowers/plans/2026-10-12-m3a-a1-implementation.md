# M3-A1 时间契约与后台导航 Implementation Plan

> **For agentic workers:** Use the executing-plans skill task by task. The approved M3-A design and six-PR delivery split are the source of truth.

**Goal:** Add a real admin workspace shell with six routes, recoverable Beijing-time filters, and a server-side range contract. Unimplemented data pages show an explicit empty state; the old running report stays available with an admin entry.

**Architecture:** FastAPI verifies Cloudflare Access JWTs and validates timezone-aware half-open ranges before returning a snapshot cutoff. A lazy React admin route owns URL filters and uses Ant Design's date picker; the existing reading routes remain separate. Later A2–A6 pages reuse these contracts.

**Tech Stack:** FastAPI, Pydantic, PyJWT, React 19, React Router 7, Ant Design 6, dayjs, Recharts 3, Vitest, pytest.

---

### Task 1: Server range contract

**Files:** `server/src/unspun/api/admin/ranges.py`, `server/src/unspun/api/admin/schemas.py`, `server/src/unspun/api/admin/auth.py`, `server/src/unspun/api/admin/__init__.py`, `server/src/unspun/api/app.py`, `server/src/unspun/core/config.py`, `server/tests/test_admin_ranges.py`, `server/tests/test_admin_auth.py`, `deploy/compose.yml`

- [x] Write tests for Beijing day across UTC dates, half-open end, future clipping, reversed and naive timestamps, invalid pagination and sort.
- [x] Run the focused test and confirm expected failures.
- [x] Implement the shared validation and a read-only `/api/admin/range` endpoint exposing `range` and `as_of`.
- [x] Require signed Access identity for the admin router; allow explicit loopback only for local preview, and test missing, spoofed, valid, wrong audience, and expired assertions.
- [x] Run focused pytest, ruff, and pyright.

### Task 2: URL filter model

**Files:** `web/src/admin/adminFilters.ts`, `web/src/admin/adminFilters.test.ts`

- [x] Test preset dates, rolling 24 hours, query serialization, invalid URL fallback, and preservation of unrelated page filters.
- [x] Run focused Vitest and confirm expected failures.
- [x] Implement pure Beijing-time interval and URL helpers.
- [x] Run focused Vitest and TypeScript checks.

### Task 3: Lazy workspace and date control

**Files:** `web/package.json`, `web/pnpm-lock.yaml`, `web/src/App.tsx`, `web/src/App.test.tsx`, `web/src/admin/AdminLayout.tsx`, `web/src/admin/DateRange.tsx`, `web/src/admin/adminApi.ts`, `web/src/admin/AdminLayout.test.tsx`, `web/src/admin/admin.css`

- [x] Test six entries, legacy `/report` entry, no fabricated data, URL restoration, and error state.
- [x] Run focused Vitest and confirm failures.
- [x] Add pinned Ant Design, dayjs, icons, and Recharts dependencies; lazy-load the workspace from the route.
- [x] Build the nav, date picker with explicit apply/cancel, server range status, clear error/empty messages, theme mapping, and return-to-reading link.
- [x] Run lint, typecheck, test, and build.

### Task 4: Reviewable local preview

**Files:** `docs/tasks/m3.md`

- [x] Run full server ruff, pyright, pytest and web lint, typecheck, test, build.
- [x] Start local preview and check direct admin route, legacy route, small viewport, and refresh/back behavior.
- [ ] Record the A1 implementation and pending user page acceptance on the task board; provide preview URL and acceptance steps. Open the page PR only after explicit user acceptance per D-012.
