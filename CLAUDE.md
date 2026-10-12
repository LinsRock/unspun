# Unspun · Personal Intelligence Station

A single-user intelligence aggregator: it pulls Chinese and English sources, then uses AI to cluster, score, and contrast viewpoints — built to break out of the filter bubble.
Requirements live in `docs/requirement.md`; milestones and acceptance criteria in `docs/roadmaps.md`. Current phase: **M3 curated intelligence and daily publishing**; task board: `docs/tasks/m3.md`. M2 was closed by user decision on 2026-10-12; outstanding evidence is tracked on both milestone boards.

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

- Always branch + PR; CI must be green before merging. Merging to main builds images, pushes them to GHCR, and deploys to the VPS.
- For any page development or modification, start a local server and provide the user with the preview URL and acceptance steps. Open the PR only after the user has experienced the page and explicitly accepted it; automated checks do not replace this acceptance gate (D-012).
- Deployment is the deploy job in `.github/workflows/ci.yml`: cloudflared SSHs into the VPS and runs `deploy/deploy.sh` (pull images, up, run migrations, health smoke check).
- Environment variables use the `UNSPUN_` prefix and are defined in `server/src/unspun/core/config.py`.

## AI development loop

Rules for AI sessions working on this repo across milestones:

- **Sources of truth**: `docs/requirement.md` (product spec) and `docs/roadmaps.md` (milestones with acceptance criteria). Both are living documents owned by the user and still evolving — treat them as the current best understanding, not a frozen contract. Requirement changes land in `docs/` first; the task board is reconciled afterwards.
- **Task board**: each milestone has `docs/tasks/m<n>.md`. At milestone kickoff, break the scope into PR-sized tasks and get the user's confirmation before implementing. Write every task self-contained (goal, touched areas, acceptance, dependencies) so a fresh session can execute it without conversation history.
- **Session protocol**: one session works one task and ends in one PR. Start by reading the task board and `docs/decisions.md`; plan before coding for non-trivial tasks; implement with tests; run the lint/typecheck/test commands above; run /code-review before opening the PR; tick the task off in the same PR that completes it.
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
