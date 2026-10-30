# Web app

The Next.js site for OpenStall Collective (spec section 3.9). So far it has the shared layout, the home page `/`, placeholder pages for `/demo`, `/seller-chat` and `/dashboard`, and a "Page not found" page for every other address. The stall, approval and status pages come in later build steps.

Built with Next.js 16 (App Router, TypeScript, Tailwind CSS 4), Vitest with React Testing Library for components, and Playwright for UI tests.

## Run it

You need Node 24.15 or newer (Node 25 is not supported: the test tools need 24.15+ or 26+). From the repo root:

```bash
cd apps/web
npm install
npm run dev
```

Open http://localhost:3000. The pages call the API at `NEXT_PUBLIC_API_BASE_URL`, which defaults to http://localhost:8000, so start the API in another terminal as the root README describes. The footer says "API online" when your browser can reach it.

- To use another API, put `NEXT_PUBLIC_API_BASE_URL=https://...` in `apps/web/.env.local` (git-ignored). Next.js bakes the value in at build time, so restart `npm run dev` or rebuild after changing it.
- The API accepts browser calls only from `WEB_BASE_URL` (default http://localhost:3000). If you open the site at another address, set `WEB_BASE_URL` for the API to match.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on http://localhost:3000 |
| `npm run build`, then `npm start` | Production build and server |
| `npm run lint` | ESLint |
| `npm test` | Vitest component and unit tests (`src/**/*.test.ts(x)`), and checks of the build setup (`build-config.test.ts`) |
| `npm run test:watch` | The same, re-run on every change |
| `npm run e2e` | Playwright UI tests (`e2e/`) |

Before every push, run `python scripts/check_all.py` from the repo root. It runs the API tests and then lint, `npm test`, `npm run build` and `npm run e2e` here, and stops at the first failure (see the root README).

## UI tests

Install the browser once:

```bash
npx playwright install chromium
```

You also need the API's Python setup from the root README. `npm run e2e` then starts its own servers and stops them when it ends:

- **API** on http://127.0.0.1:8100, with `OPENSTALL_MODE=fake`, `WEB_BASE_URL` set to the e2e site, and `DATABASE_URL` pointing at a fresh SQLite file in `apps/web/.e2e-data/`. It runs with the repo's `.venv` Python when there is one (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere), otherwise with `python` from PATH. Set `E2E_PYTHON` to use another one.
- **Web** on http://127.0.0.1:3100: a production build (`npm run build` with `NEXT_PUBLIC_API_BASE_URL` set to the e2e API) served by `npm start`, which is steadier than the dev server. It is built into `.next-e2e/` (`NEXT_DIST_DIR`, read by `next.config.ts`), so your own build in `.next` is left alone and `npm start` still serves it.

The tests never reuse a server that is already running, and their ports differ from the dev servers' 8000 and 3000, so you can keep `npm run dev` and the API running while they run. If a port is taken, set `E2E_API_PORT` or `E2E_WEB_PORT`.

Everything the tests write is git-ignored:

- `.next-e2e/`: the production build the tests run against.
- `playwright-report/`: the HTML report. Open it with `npx playwright show-report`.
- `test-results/`: traces and screenshots of failed tests.
- `e2e/screenshots/`: every page at 375px and 1280px wide, saved by `responsive.spec.ts` on each run for a quick look at the layout.

**Writing UI tests:** with Cache Components, pages you navigate away from stay in the DOM, hidden. Find elements with `getByRole`, `getByLabel` or `getByText`, which skip hidden elements, or add `.filter({ visible: true })` to a CSS locator. A plain CSS selector can match the hidden copy.

## Notes for contributors

- **Next.js 16 is newer than most guides.** The docs for the installed version are in `node_modules/next/dist/docs/`. Read them before using an API you know from an older version.
- **Cache Components and Partial Prefetching are on** (create-next-app's defaults, and always on from the next major version). Server-side data is fetched at request time unless you cache it with `"use cache"`. Code that reads request data or URL params on a dynamic route needs a `<Suspense>` boundary, or `next build` fails. The header's navigation shows the pattern.
- **Calling the API:** use `apiGet` and `apiPost` from `src/lib/api.ts`. They throw an `ApiError` whose message can be shown to people as it is.
- **Colours** are CSS variables in `src/app/globals.css`, with light and dark values, used as Tailwind classes such as `bg-surface`, `text-muted`, `border-border` and `bg-accent`.
- **Fonts** (Geist) come from the `geist` npm package through `next/font/local`, so `npm run build` and the UI tests work offline once `npm install` has run.
- **Test file names** must be unique across the whole repo, Python tests included.

```
src/app/          pages (App Router) and their tests
src/components/   shared components, each test next to its component
src/lib/api.ts    typed fetch wrapper for the API
e2e/              Playwright specs; e2e/support/ holds their helpers
```
