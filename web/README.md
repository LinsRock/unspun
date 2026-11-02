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

## PWA and offline app shell

The production build generates `sw.js` and `manifest.webmanifest`. Workbox
precaches the app shell; offline SPA routes use the cached HTML. API and
Cloudflare Access paths are excluded from navigation fallback. Service workers
are disabled during development; use the production preview for offline tests.

Historical event and digest pages are retired. App startup removes only the old
`unspun-digests` IndexedDB entry and `unspun.feed-preferences.v2` local storage
entry; other data and the theme remain. Unavailable storage does not block
reading, and a later startup retries cleanup. Current API responses are not
persisted; content and source links need a network connection.

Install through the browser's install menu or iOS Safari's Add to Home Screen.
First log in online through Cloudflare Access. The installed app opens `/` and
uses the current discovery or independent reading page. Retired `/history`,
`/events` and `/digest` links redirect to that home. Offline startup displays the
current reading shell; reconnecting resumes queries.

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
installed-app start URL, checks retired route redirects and reconnects. It also
checks targeted cache cleanup, mobile overflow and API navigation exclusion. CI runs
the same check after building. It does not replace phone installation acceptance.
