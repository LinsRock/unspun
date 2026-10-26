# Unspun

A single-user app for automatic discovery and curation of important developments and personally interesting articles, videos, posts, and discussions. Chinese-language sources and domestic platforms come first, with global coverage and a small set of international sources.

## Read only what the task needs

Start with `docs/README.md`, then the relevant task section and its specification. Search `docs/decisions.md` for applicable decisions instead of reading the entire log. Do not recursively read `docs/`, all task boards, or every evidence link. `docs/.ignore` keeps historical documents and evidence out of ordinary ripgrep results; read an explicit path or use `rg --no-ignore <pattern> <evidence-directory>` when needed. Historical entries and recovery are indexed in `docs/archive/README.md`.

## Current boundaries

Product status lives in `docs/tasks/r2.md`: R1 closed; R2-00–03 and R2-05 delivered; R2-04 incomplete; R2-06 remains **3/4, real quality incomplete, v6 semantics unmeasured, overall user acceptance null**. R2-06 is deferred; R2-07 has its first backend delivery deployed at `1d92421` / schema `000020`, with processing/publication off and real quality incomplete. R2-08 has its first hybrid backend deployed at `13b6fdd`, with the entry default off; delivery evidence is in `docs/acceptance/r2-08-hybrid-feed-2026-10-23.md`. R2-09 backend and R2-10 reading pages are delivered with all production R2 gates closed; the page acceptance and delivery record is linked from `docs/tasks/r2.md`. R2-11 has a bounded existing-content reading rollout PR prepared, pending explicit enablement authorization; do not merge it or change production gates before that authorization. See its task-board handoff for switches and rollback. R3 is pending. Do not resume legacy M3 work from historical plans.

R2-07 follows D-041 and `docs/superpowers/specs/2026-10-23-r2-07-progress-overview.md`; its engineering evidence is in `docs/acceptance/r2-07-progress-overview-2026-10-23.md`. Use reviewed manual member versions in isolation, independent of unaccepted automatic membership. Mock responses are engineering evidence only. Processing/publication default off; no allocation means rejection and other stages cannot fund this chain. Models, budgets, paid-stop, reservations and historical data stay protected.

R2-06 manual corrections and the bounded v6 evaluation entry were deployed as `e48454a` (PR #131). Current delivery and blockers are in `docs/acceptance/r2-06-completion-2026-10-22.md`; read its linked execution registration before continuation. Keep the v6 contract fixed, automated member processing/allocation off and all R2-06 paid phases stopped. Do not automatically repair, retry, resume budgets, convert old tasks, prepare new blind samples or activate production. Preserve unknown reservations, cumulative pools, frozen evidence, old failures and user rating nulls. Provider queries/reconciliation and paid execution still require their separate authorization, genuine per-request receipts and completed execution review. The older `r2-06-exit` record/checker describes its frozen 2026-10-21 snapshot, not current backend delivery.

The user requested documentation cleanup (CL-02); use `docs/tasks/cleanup.md`. Keep active fixtures, registered dependencies, original model outputs, unresolved fee evidence and paid-stop files at their original paths and bytes. The user approved moving obsolete process artifacts to fixed Git history; follow `docs/acceptance/README.md`. Do not commit routine lint/test/build logs, JUnit output, CI status dumps or whole-environment snapshots. Record concise results and CI links instead. CL-01 retired the legacy worker; shared code, development resources and data have separate CL-03–06 scopes. Preserve historical reading, active previews/editable targets and R2-04 observation resources. Recommendation expiry does not authorize data deletion.

## Architecture and layout

Browser -> Cloudflare Access -> Tunnel -> VPS. The tunnel targets
`127.0.0.1:8080`, the only published port. Caddy serves the React app and proxies
`/api/*` to FastAPI; the API and controlled `r1-worker` share Postgres + pgvector.

- `server/`: Python; `unspun.api`, `unspun.pipeline`, shared `unspun.core`.
- `web/`: React, Vite, strict TypeScript, Tailwind, oxlint and Vitest.
- `config/`: source lists, weights and scoring parameters; tune these here.
- `deploy/`: Dockerfiles, Compose overlays, Caddy and deploy script.
- `docs/`: user-owned product direction, requirements and delivery checklists.

Environment variables use `UNSPUN_`; definitions are in `server/src/unspun/core/config.py`.

## Common commands

```bash
# server/
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv run alembic revision --autogenerate -m "..."
uv run uvicorn unspun.api.app:app --reload  # :8000

# web/
pnpm install
pnpm lint && pnpm typecheck && pnpm test
pnpm dev  # :5173, /api proxied to :8000

# repository root; local r1-worker defaults to 0
docker compose -f deploy/compose.yml -f deploy/compose.local.yml up --build
```

## Workflow and validation

- Always branch + PR; selected CI checks and `required-checks` must pass before merging. Work through approved batches without extra intermediate approval. Reconcile origin/main before opening a PR.
- R2 page changes require a real-API local preview and explicit user acceptance before a PR (D-012). R1's AI-managed intermediate delivery exception (D-025) does not extend to R2. Documentation and backend work follow review/CI without additional per-task approval.
- Requirements belong in `docs/product-definition.md` and `docs/requirement.md`, delivery order in `docs/roadmaps.md`. Distinguish confirmed requirements, suggestions and observed implementation. Change requirements first, then reconcile the task board. Milestone completion needs user confirmation before starting the next one.
- Plan non-trivial code. Keep recovery/concurrency and budget/accounting independently reviewable; related task IDs may share a PR (D-026). Record a short result and evidence link, not repeated delivery histories.
- Read applicable decisions before architecture/dependency changes. Record significant choices in `docs/decisions.md`; propose reversals to the user instead of silently overriding them.
- Run affected checks while iterating and relevant full regression before merging. Review the diff and affected callers once; after fixes, review the additional diff and rerun affected checks. Repeat full review/regression only for material changes or unresolved concerns. For explanation-only docs, check links, state, diff and CI scope; do not run unrelated application tests.
- Reuse test images, dependency caches, evaluation inputs and tools. Avoid general frameworks or duplicate historical reports for one-off checks. Source observation may start before downstream implementation; publication still needs G2. Preserve migration, recovery, accounting, grounding and real reading/feedback validation.

CI routing is defined in `.github/scripts/ci_scope.py`. Explanation-only docs do not build runtime images; evaluation inputs/tools run backend checks, prototype changes run their own checks. CI/build changes and unknown build inputs take the conservative full path. Main deploys cumulative runtime changes since the verified production baseline, reuses immutable unchanged images, and skips obsolete runs. Missing history falls back to all checks/builds; `workflow_dispatch` checks without publishing (D-026).

Deployment runs through `.github/workflows/ci.yml` and `deploy/deploy.sh`: resolve images, wait for DB, migrate with the target image, check budgets/preflight, start services and verify the target API version. APP_VERSION identifies the assembled release; unchanged component images can retain earlier revisions. Keep the retired worker absent during deployment and rollback; use retired-service deployment files, not old Compose definitions. Production retains one controlled R1 consumer within registered source/material/budget limits (D-025/D-029/D-033).

## Language, commits and PRs

- English throughout the repository except Chinese product documentation in `docs/` and user-facing UI copy/test assertions in `web/src/`. Code comments stay English. CI enforces this.
- Conventional Commits: `type(scope): subject`; imperative, lowercase, no final period, at most 72 characters. Types: feat, fix, docs, ci, build, refactor, test, perf, chore. Optional scopes: server, web, deploy, config, docs. Bodies explain why; breaking changes use `BREAKING CHANGE:`.
- PR titles follow the same format; use `.github/pull_request_template.md` (Summary / Changes / Testing). Keep PRs small and single-topic. Never rewrite published history.

## Hard rules

- No secrets in the repository or CI logs. Production secrets live only in `~/unspun/.env` on the VPS.
- Schema changes use Alembic; dropping tables or columns needs explicit user confirmation before merging.
- Never hand-edit production containers or data; changes go through a PR.
- Production publishes only `127.0.0.1:8080`.
- Prompt or scoring changes must pass the standard event-set evaluation before merging.
- Cleanup uses `docs/tasks/cleanup.md`: verify references, ownership, active use, frozen evidence and recovery. Preserve accounting, unresolved reservations, identity/feedback/task/quota semantics and required historical reading. Do not clear reservations, historical failures or user rating nulls to make checks pass.
