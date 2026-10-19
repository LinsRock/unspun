# Unspun

A single-user app for automatic discovery and curation of important developments and personally interesting articles, videos, posts, and discussions. Domestic platforms and Chinese-language sources come first; content can cover the world, with a small set of international sources supplementing coverage.
Current phase: **R2-02 bounded metadata scanning and processing quotas**, following the read-only R2-01 baseline (2026-10-19) and D-030. The entry point is `docs/tasks/r2.md`; the quota contract is in `docs/superpowers/specs/2026-10-19-r2-02-scan-quotas.md` and evidence in `docs/acceptance/r2-02-scan-quotas-2026-10-19.md`. Eight existing sources explicitly opt into separate scan/material/card quotas without changing their enabled stages, material scopes, models or budgets. Legacy `max_items` and unconfigured R1 behavior remain compatible. R2-01 v1 evidence and missing user ratings stay frozen; R2-03 onward and R3 remain pending. R1 is closed at 19/19 with qualified user acceptance; `docs/tasks/r1.md` retains its historical evidence. R1's final-only acceptance exception does not extend to R2 page changes. Confirmed direction is in `docs/product-definition.md`; requirements and roadmap remain user-owned. Do not resume legacy M3 work automatically.
The user confirmed a recommendation-first feed with a latest switch, and daily selections that update when important new content arrives (D-024). Requested sources and validation status live in `docs/source-plan.md`; this list is distinct from the enabled runtime configuration. WeChat public accounts and Xiaohongshu are later exploration items.
Cross-milestone retirement and cleanup are scheduled in `docs/tasks/cleanup.md` (D-031): inventory first; retire the legacy worker after R2-03; simplify the old event chain and eligible data after R2 acceptance; retire the old digest after R3 acceptance. Documentation and unused development resources have separate cleanup tasks. Scheduling these tasks does not execute deletions or change the next product task, R2-03.

## Architecture

```
Browser → Cloudflare Access (login) → Cloudflare Tunnel → VPS
  cloudflared on the VPS points at 127.0.0.1:8080 (web container, the only published port)
  web (Caddy: static files + /api/* reverse proxy) → api (FastAPI) → db (Postgres+pgvector)
  worker (pipeline, same image as api with a different command) → db
```

## Layout

| Directory | Contents |
| --- | --- |
| `server/` | Single Python project: `unspun.api` (FastAPI), `unspun.pipeline` (pipeline), `unspun.core` (config/logging/DB, shared by both) |
| `web/` | React SPA: Vite + TypeScript strict + Tailwind, oxlint + Vitest |
| `config/` | Source list, weights, scoring parameters (day-to-day tuning happens here, not in code) |
| `deploy/` | Dockerfiles, Compose (base + local/prod overlays), Caddyfile, deploy.sh |
| `docs/` | Requirements and roadmap, in Chinese (the task book — change requirements there first) |

## Common commands

```bash
# in server/
uv sync                 # install dependencies
uv run ruff check . && uv run ruff format .
uv run pyright          # strict mode
uv run pytest
uv run alembic revision --autogenerate -m "..."   # create a migration
uv run uvicorn unspun.api.app:app --reload        # run the API locally (:8000)

# in web/
pnpm install
pnpm lint && pnpm typecheck && pnpm test
pnpm dev                # local dev (:5173, /api proxied to :8000)

# repo root: full local stack (db + api + worker + web)
docker compose -f deploy/compose.yml -f deploy/compose.local.yml up --build
```

## Workflow

- Always branch + PR; selected CI checks and `required-checks` must pass before merging. Main publishes only cumulative runtime changes, builds affected images, and reuses immutable running references for unchanged services (D-026).
- R1 used AI-managed intermediate PRs and final user acceptance (D-025). R2 page changes still require a real-API local preview and explicit user acceptance before opening a PR (D-012); documentation and backend work follow the existing review and CI process without additional per-task approval.
- Keep the legacy production AI worker disabled. Ordinary deployments, diagnosis, and rollback must not restart it. The controlled R1 runtime retains its registered source, material, and budget boundaries; R2 kickoff does not expand them. See D-025, D-029, and the worker shutdown record.
- Deployment is the deploy job in `.github/workflows/ci.yml`: cloudflared SSHs into the VPS and runs `deploy/deploy.sh` (resolve release images, wait for DB, migrate with the target image, start services with zero legacy workers, check the target API version).
- Environment variables use the `UNSPUN_` prefix and are defined in `server/src/unspun/core/config.py`.

CI routes checks by changed paths. API contracts and server dependency changes also check the frontend; archived prototypes run only for their own changes. Explanation-only docs do not themselves trigger runtime builds. Evaluation inputs/tools still run backend checks. CI/build configuration changes run all checks, and unknown build inputs take the conservative full path. Main uses paginated production deployment history, verifies the actual deployment step ran, and includes paths touched since that baseline (even reverted changes), so partial failures and rollbacks are not lost. Missing release history falls back to checking/building all inputs. `workflow_dispatch` runs all checks without publishing. Obsolete main runs skip deployment; actual deployment and migration checks remain required. APP_VERSION identifies the assembled release; component image references may retain earlier unchanged revisions.

## AI development loop

Rules for AI sessions working on this repo across milestones:

- **Sources of truth**: `docs/product-definition.md` (confirmed direction and design suggestions), `docs/requirement.md` (product spec), and `docs/roadmaps.md` (delivery batches and acceptance). These are living documents owned by the user — distinguish confirmed requirements from proposed defaults and observed implementation. Requirement changes land in `docs/` first; the task board is reconciled afterwards.
- **Task board**: each milestone has a self-contained board under `docs/tasks/`. Confirm scope at kickoff. Start R2 from `docs/tasks/r2.md`; task IDs are acceptance checklists, and related items may share a delivery PR. Keep recovery/concurrency and budget/accounting independently reviewable; split oversized batches when necessary. R1's historical delivery grouping is recorded in D-026.
- **Retirement and retention**: use `docs/tasks/cleanup.md` for legacy code/workers, superseded documents, development residue, and unused or stale data. Verify references, ownership, active use, frozen evidence, and recovery before a specific cleanup batch. Recommendation expiry is separate from storage deletion. Keep accounting, unresolved reservations, identity/feedback/task/quota semantics, and required historical reading intact; preserve the existing confirmation rule for schema drops.
- **Session protocol**: work through approved delivery batches without intermediate user approval. Read the current task board and decisions before each batch and reconcile origin/main before opening its PR. Plan before non-trivial code; run affected checks during iteration and the relevant full regression before merging. Review the diff and affected callers once; after fixes, review the additional diff and rerun affected checks. Repeat full review/regression only for material new changes or unresolved concerns. Update completed checklists and concise new evidence in the same PR.
- **Execution cost**: reuse existing test images, dependency caches, evaluation inputs, and validation tools. Do not build a general framework or duplicate historical reports for a one-off check. Start read-only source observation as soon as adapters work, in parallel with downstream development; G2 still gates publication. Continue independent implementation while CI runs unless it needs that deployment. Keep migration, recovery, accounting, grounding, and real reading/feedback validation.
- **Decision log**: `docs/decisions.md` records significant technical choices and why they were made. Check it before proposing architecture or dependency changes; never silently reverse a recorded decision — propose the change to the user and update the log entry instead.
- **Milestone close**: reconcile `docs/` with what was actually built, record acceptance results on the task board, and confirm with the user before starting the next milestone.

## Language conventions

- Everything in the repo is written in English, with two exemptions:
  - `docs/` — product documentation stays in Chinese.
  - User-facing UI copy in `web/src/` — the product UI is Chinese; test assertions follow the UI copy. Comments in `web/src/` are still English.
- English applies to code, comments, config comments, CI, scripts, log and error messages, commit messages, and PR titles/descriptions.
- CI enforces this with a CJK scan that fails on Chinese text outside the exemptions above.

## Commit & PR conventions

- Commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): subject` — imperative mood, lowercase subject, no trailing period, ≤72 characters.
  - Types: `feat` `fix` `docs` `ci` `build` `refactor` `test` `perf` `chore`.
  - Optional scopes: `server` `web` `deploy` `config` `docs`.
  - The body explains why, not what. Breaking changes use a `BREAKING CHANGE:` footer.
- PR titles use the same Conventional Commit format (squash merges turn the title into the commit subject); CI validates the title.
- Keep PRs small and single-topic, and fill in the PR template (Summary / Changes / Testing).
- Never rewrite published history; pre-convention Chinese commits stay as they are.

## Hard rules

- No secrets in the repo or in CI logs. Production secrets live only in `~/unspun/.env` on the VPS.
- Database schema changes must go through Alembic migrations; migrations that drop tables or columns need explicit user confirmation before merging.
- Never hand-edit containers or data on the production server; every change goes through a PR.
- Never publish any host port other than `127.0.0.1:8080` (production).
- Changes to prompts or scoring logic (from M3 on) must pass the standard event-set evaluation before merging.
