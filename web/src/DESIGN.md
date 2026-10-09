# Unspun design spec (T-D1)

Visual language for all frontend work from M2 on. Tokens live in
`web/src/theme.css`; the user-approved interactive prototype (the source of
truth for look and layout) is archived at `docs/design/t-d1-prototype.html` —
open it in a browser, desktop and phone width, light and dark.

Direction: modern-tool restraint (Vercel-like) on a warm paper base, with the
information structure of an intelligence feed (reference: aihot.news). Dark
mode is neutral cool grey — the paper tint is a light-mode-only trait.

## Color

Use Tailwind utilities generated from tokens (`bg-surface`, `text-ink-2`,
`border-line`, ...). Never hardcode a color in a component.

| Token | Role |
| --- | --- |
| `bg` / `bg-sunk` | page ground / sunken areas (breakdown panel, day bar, collapsed bars) |
| `surface` / `surface-2` | cards / sidebar & secondary chrome |
| `line` / `line-strong` | all borders (always 1px) / hover borders |
| `ink` … `ink-4` | 4-step text scale: titles, body, secondary, metadata |
| `accent`, `accent-ink`, `accent-soft` | the only interaction color: links, active nav, viewpoint entry |
| `hot`, `amber`, `ok` (+`-soft`) | semantic only — score tiers, failures, budget OK. Never decorative. |

Score tiers: >= 80 `hot`, 65–79 `amber`, below neutral (`bg-sunk` + `ink-3`).

## Theming

Three states: `data-theme="light"` / `"dark"` on `<html>`, or no attribute
(follow system). `theme.css` carries only the CSS side (the manual attribute
beats the OS setting in both directions). The JS side — the 3-state switcher
(bottom of sidebar / top bar corner on mobile), applying `data-theme`, and
persisting the choice to `localStorage` — ships with T-D2; the prototype has
a reference implementation. `color-scheme: dark` is also deferred to T-D2 so
unstyled pages keep rendering light until restyled.

## Typography

System stack with PingFang SC (zero font download); data uses the mono stack.

| Size / weight | Use |
| --- | --- |
| 20px / 700 | page title |
| 15px / 650 | event card title, line-height 1.5 |
| 14px / 400 | body, digest intro, line-height 1.65–1.85 |
| 13.5px / 400 | card summary, in `ink-2` |
| 12–12.5px | tags, source chips, action bars |
| 11–12px mono | metadata, timestamps, counts, costs — `font-mono tabular-nums` |

All numbers that line up (scores, costs, counts, times) are mono + tabular.

## Spacing, shape, density

- 4px grid: 8/12/16 inside components, 10px between cards, 24px between blocks.
- Radius: cards `rounded-card` (10px), controls `rounded-ctl` (8px), tags/pills full.
- Borders always 1px; shadows only in light mode and only subtle (`shadow-card`).
- Density is medium-high: a card shows title + tags + summary by default;
  score breakdown and the full source list are collapsed inside the card;
  a wide screen shows ~5 events per viewport.

## Core components (see prototype for exact rendering)

- **Event card**: title row (title + score badge right), meta row (tags +
  `N 源 · 更新时间` in mono), summary, collapsed breakdown, 2 source chips,
  action row.
- **Score badge**: mono bold, tinted per tier; tapping toggles the breakdown
  panel (bar rows: importance, objective + indented sub-scores, reason line).
- **Tags**: region = outlined chip, kind = `bg-sunk` chip, language = tiny
  mono mark on source chips. The meta row carries metadata only — no actions.
- **Action bars** (card bottom, one row, wrap on narrow): left "另有 N 篇来源报道"
  (`bg-sunk`), right "◫ 观点对比 · N 源说法" (`accent-soft`, semibold). This
  order is a user decision — keep it.
- **Viewpoint page**: claim columns `grid minmax(240px, 1fr)` (stack on
  mobile), each column = source head + stance + link to the article;
  divergence list numbered in `hot` mono; generation metadata in mono.
- **Digest**: intro card with 3px accent left border + generation metadata;
  ranked list (rank 1 `hot`, rank 2 `amber`, rank 3 `ink-2`, rest `ink-4` —
  tokens only), score badge per item, viewpoint excerpt in `accent-soft`.
- **Report**: stat tiles (mono values, semantic colors), bordered tables,
  status dots.
- **Navigation**: desktop 216px left sidebar (`surface-2`); mobile top bar +
  bottom tab bar (feed / digest / report). Feed has filter pills (active =
  inverted `ink`) and a day bar.

## Rules

1. One interaction color (accent). Semantic colors never decorate.
2. Metadata rows never contain actions; actions live in the card action row.
3. Everything numeric is mono + tabular.
4. Any new UI must work at 400px width with 16px gutters, no horizontal scroll.
