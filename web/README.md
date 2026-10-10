# Unspun web

React SPA with Vite, TanStack Query and React Router. API requests proxy to
`http://localhost:8000` during development and preview.

```bash
pnpm install --frozen-lockfile
pnpm dev
pnpm lint && pnpm typecheck && pnpm test
pnpm build
pnpm preview --host 0.0.0.0 --port 4173
```

## PWA and offline digests

The production build generates `sw.js` and `manifest.webmanifest`. Workbox
precaches the app shell; offline SPA routes use the cached HTML. API and
Cloudflare Access paths are excluded from navigation fallback. Service workers
are disabled during development; use the production preview for offline tests.

Previously loaded, nonempty digest responses persist in IndexedDB, including
historical dates and the date corresponding to the latest digest. Empty and
failed responses without data, event feed queries and reports are not persisted.
A failed background refresh retains the last digest snapshot. The persisted
query cache expires after seven days without an update; its schema version is
`digest-v1` (increment it when the stored response shape becomes incompatible).
Unavailable storage falls back to online use. Clearing site data removes offline
digests. Source links still need a network connection.

Install through the browser's install menu or iOS Safari's Add to Home Screen.
First log in online through Cloudflare Access and open the desired digest.
The installed app opens `/digest`. Offline dates without a cached snapshot show
an explanation; reconnecting resumes the query.

Installation and service workers require HTTPS or a localhost origin. A phone
opening a LAN HTTP URL can preview layout but cannot test installation or offline
restart. Use the HTTPS production origin for the phone's final flight-mode test.

## Production browser check

With `pnpm preview --port 4173` running:

```bash
pnpm exec playwright install chromium
pnpm test:pwa
# Optional: PWA_BASE_URL=http://127.0.0.1:4173 pnpm test:pwa
```

This uses an isolated browser context and API fixtures, checks installation
assets, then goes offline, closes the original tab, reopens and reloads the
installed-app start URL, switches to an uncached date and reconnects. It also
checks mobile overflow, source links and the API navigation exclusion. CI runs
the same check after building. It does not replace phone installation acceptance.
