# M3-A2 History Query Implementation Plan

> **For agentic workers:** Use the approved M3-A delivery plan and admin workspace design as the product contract. Execute these tasks in order, with tests before implementation.

**Goal:** Deliver authenticated, read-only source, article, and event history with filters, stable pagination, details, safe CSV export, and responsive navigation.

**Architecture:** Reuse A1's Access-protected admin router and half-open UTC range resolver. Query existing Postgres tables without fabricating historical source configuration or event timestamps. Keep list responses narrow and load content, evidence, and viewpoints only for details. Store page filters in the URL while sharing only range parameters between sidebar pages.

**Tech Stack:** FastAPI, SQLAlchemy/Postgres, Pydantic, React, TypeScript, TanStack Query, Ant Design, Vitest, pytest.

---

### Task 1: Backend query contracts and source history

**Files:** `server/src/unspun/api/admin/sources.py`, `server/src/unspun/api/admin/query.py`, `server/src/unspun/api/admin/__init__.py`, `server/tests/test_admin_sources.py`

- [ ] Add integration tests for current and removed source IDs, successful zero-update fetches, latest error ordered by `(run_at, id)`, unknown success rate for no runs, whitelist sorting, and stable pagination.
- [ ] Run `uv run pytest tests/test_admin_sources.py -q` and confirm failures.
- [ ] Add source list/detail DTOs and common bounded pagination/range query helpers. Aggregate fetch outcomes and article counts inside the selected range; read current metadata only from `load_sources()`. Mark removed IDs as no longer configured and do not invent their historical metadata.
- [ ] Run the focused tests and commit `feat(server): add source history queries`.

### Task 2: Article and event history

**Files:** `server/src/unspun/api/admin/content.py`, `server/src/unspun/api/admin/__init__.py`, `server/tests/test_admin_content.py`

- [ ] Add integration tests for article fetched/reported time filters, missing publication time, escaped keyword search, status and quality filters, stable `(timestamp, id)` pagination, event article/source counts, missing report time, and foreign viewpoint claim removal.
- [ ] Run `uv run pytest tests/test_admin_content.py -q` and confirm failures.
- [ ] Add paginated article and event list endpoints plus detail endpoints. Select only list columns in list queries. Use valid article `published_at` values for event earliest/latest reported time, never `first_seen_at` or `changed_at` as a reported timestamp. Include full text, grounding, score details, articles, and membership-checked viewpoint claims only in details.
- [ ] Run the focused tests and commit `feat(server): add content history queries`.

### Task 3: Safe exports and indexes

**Files:** `server/src/unspun/api/admin/exports.py`, `server/src/unspun/api/admin/__init__.py`, `server/alembic/versions/20261012_000008_admin_history_indexes.py`, `server/tests/test_admin_exports.py`

- [ ] Add tests proving exports reuse list filters, cap rows, produce correct CSV columns, and neutralize leading spreadsheet formula characters.
- [ ] Run `uv run pytest tests/test_admin_exports.py -q` and confirm failures.
- [ ] Add streaming CSV endpoints for sources, articles, and events. Add only indexes justified by their time/source and stable sort predicates after inspecting query plans.
- [ ] Run focused tests and commit `feat(server): export filtered admin history safely`.

### Task 4: Source page and drilldown

**Files:** `web/src/admin/SourcesPage.tsx`, `web/src/admin/SourceDetail.tsx`, `web/src/admin/adminHistoryApi.ts`, `web/src/admin/AdminLayout.tsx`, `web/src/admin/admin.css`, `web/src/admin/SourcesPage.test.tsx`

- [ ] Add UI tests for failure/empty states, source sorting/filtering, page navigation, and source-to-article drilldown with range preserved.
- [ ] Run `pnpm test src/admin/SourcesPage.test.tsx` and confirm failures.
- [ ] Build the responsive source summary/table/detail drawer. Keep filter and page state in URL; use `AbortSignal` with TanStack Query; show current configuration separately from period results. Add CSV action.
- [ ] Run focused tests and commit `feat(web): add source history page`.

### Task 5: Article/event page and details

**Files:** `web/src/admin/ContentPage.tsx`, `web/src/admin/ArticleDetail.tsx`, `web/src/admin/EventDetail.tsx`, `web/src/admin/adminHistoryApi.ts`, `web/src/admin/AdminLayout.tsx`, `web/src/admin/admin.css`, `web/src/admin/ContentPage.test.tsx`

- [ ] Add UI tests for tabs, time basis, filters, pagination, article-to-event navigation, missing timestamps, and responsive detail states.
- [ ] Run `pnpm test src/admin/ContentPage.test.tsx` and confirm failures.
- [ ] Build article/event tables and detail drawers with safe external links, URL-restored filters, preserved shared range, and filtered CSV actions. Explicitly label missing or unavailable historical data.
- [ ] Run focused tests and commit `feat(web): add article and event history pages`.

### Task 6: Integration and preview

**Files:** `docs/tasks/m3.md` and any small fixes discovered by verification.

- [ ] Run server Ruff, Pyright, pytest with a migrated Postgres database; run web lint, typecheck, test, and build.
- [ ] Start API and Vite preview with local-only admin preview enabled and seeded data. Check desktop and 400px, light/dark, source-to-article-to-event navigation, filters, export, URL back/forward, empty/error states.
- [ ] Request user page experience and explicit acceptance under D-012 before creating the PR. Record acceptance on the task board in the same PR.
