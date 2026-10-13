# M3-A6 Overview Implementation Plan

**Goal:** Replace the empty admin home with a real, drillable overview of current health, period output, costs, trends, and exceptions.

**Architecture:** A read-only FastAPI endpoint resolves one Beijing range and aggregates existing content, source, run, backlog, and cost data. The React page renders that response with Recharts and links into the existing detail pages. Current health is explicitly separate from period metrics.

**Tech Stack:** FastAPI, SQLAlchemy, React, TypeScript, TanStack Query, Ant Design, Recharts, Vitest, pytest.

## Tasks

- [x] Add database-backed overview tests for count/cost agreement, range boundaries, missing run fields, and errors.
- [x] Implement `/api/admin/overview` with one resolved range and current-state labels.
- [x] Add UI tests for real metrics, unavailable totals, range-preserving drilldowns, and retry.
- [x] Implement overview cards, accessible trends and breakdown, responsive layout, and navigation.
- [x] Run server and web static checks, database tests, frontend tests, and production build.
- [x] User accepted the initial local preview on 2026-10-13.
- [ ] Re-review updated trends (hour/day/month and processing status), present the local preview, and receive acceptance before opening a PR or marking A6 complete.
