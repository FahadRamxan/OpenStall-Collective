# Decisions

Design decisions and the reasons for them, newest section last. Add to this file when you make a choice that someone would otherwise have to rediscover.

## October 30: the web app and its tests (prompt 02)

**Next.js 16 with create-next-app's defaults, Cache Components included.** `apps/web` was created with create-next-app 16.4 (TypeScript, App Router, Tailwind CSS 4, ESLint, `src/`, `@/*`). Its defaults turn on Cache Components and Partial Prefetching. We kept them: they are the default for new apps and become always on in the next major version, and they make server-side data dynamic unless cached, so `next build` never needs a running API. The cost:

- Anything that reads request data or unknown URL params needs a `<Suspense>` boundary, or `next build` fails. This includes `usePathname()` in the header on dynamic routes such as `/stall/[id]`, so the header's navigation is already wrapped in one (checked with a temporary dynamic route: without the boundary the build fails with `CLIENT_HOOK_DYNAMIC`).
- Pages you navigate away from stay in the DOM, hidden. UI tests find elements by role, label or text, which skip hidden elements.

We did not add the `AGENTS.md` and `CLAUDE.md` files that create-next-app can generate: agent instruction files are the team's call. `apps/web/README.md` points to the docs bundled in `node_modules/next/dist/docs/` instead.

**Vitest 5 with jsdom and React Testing Library.** Vitest runs `src/**/*.test.ts(x)` and the build-config checks next to `package.json` (`*.test.ts`), so it never picks up the Playwright specs in `e2e/`. The `@/*` alias resolves through Vite's own `resolve.tsconfigPaths` option, so the `vite-tsconfig-paths` plugin from the Next.js guide is not needed. The tests need Node 22.22.2+, 24.15+ or 26+ (jsdom 30 skips Node 25), so `package.json` asks for `^24.15.0 || >=26.0.0` and the READMEs say Node 24.15 or newer.

**No CI: one local command is the gate.** GitHub Actions can't run on the repo owner's account, so `scripts/check_all.py` runs every check before a push: `pytest`, then `npm run lint`, `npm test`, `npm run build` and `npm run e2e` in `apps/web`. It stops at the first failure and prints which checks passed, failed or did not run. It finds the repo from its own path, runs pytest on the repo's `.venv` Python when there is one (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere, else the Python running it), passes that Python to the UI tests as `E2E_PYTHON`, and calls npm by the full path `shutil.which` finds (`npm.cmd` on Windows), never through a shell. We left `.github/workflows/ci.yml` as prompt 01 made it; removing it is a separate change. Later prompts add their checks to this script.

**UI tests run against their own servers.** Playwright starts the API on 127.0.0.1:8100 and the web app on 127.0.0.1:3100 (overridable with `E2E_API_PORT` and `E2E_WEB_PORT`) and never reuses a server that is already running, so a dev server on 8000 or 3000 can neither collide with the tests nor leak into them. Prompt 02 asked for 8000 and 3000; with those, `npm run e2e` and `check_all.py` would fail whenever the dev servers are running, which is most of the time. The web app is a production build served by `next start`, which is steadier than the dev server and is what we deploy; `NEXT_PUBLIC_API_BASE_URL` is set for that build, because Next.js bakes it in. Tests run one at a time because they share one API and one database.

**The UI tests build into `.next-e2e/`, not `.next`.** Their build talks to the e2e API, so in `.next` it would replace your own build, and `npm start` would then serve a site whose footer says the API is offline. `playwright.config.ts` sets `NEXT_DIST_DIR=.next-e2e` for the web server, and `next.config.ts` uses it as `distDir`. `tsconfig.json` lists `.next-e2e/types/**/*.ts` and `.next-e2e/dev/types/**/*.ts` up front, because otherwise `next build` adds them itself and changes a tracked file on every first run. ESLint and git ignore the folder. `build-config.test.ts` checks all of this.

**The e2e database starts empty on every run.** The API gets `DATABASE_URL` pointing at a SQLite file in `apps/web/.e2e-data/` (git-ignored). A small script in the API server's start command empties that folder just before the API starts. It is not done in `playwright.config.ts`, because Playwright loads the config in several processes, in UI mode even while the servers are running.

**Which Python runs the e2e API.** `E2E_PYTHON` if set, otherwise the repo's `.venv` (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere), otherwise `python` from PATH.

**Geist comes from the `geist` npm package, not Google Fonts.** `next/font/google` downloads fonts during `next build`, so every build, and with it `npm run e2e` and `check_all.py`, needed internet access. The `geist` package (Vercel's, SIL Open Font License) ships the font files and loads them with `next/font/local`. It is pinned to 1.8.1 in the lockfile; 1.9.0 was hours old when we added it.

**CORS allows exactly one origin.** The API accepts browser calls only from `WEB_BASE_URL` (default http://localhost:3000, trailing slash removed because browsers send the origin without one), with no cookies. The MCP endpoint keeps its own host and origin checks.

**The footer checks the API.** A small status line in the footer calls `/health` through `src/lib/api.ts`. It is the first real use of the fetch wrapper, and the UI test that expects "API online" proves the API address baked into the build and the API's CORS setting fit together. Every visitor sees it, judges included, so when the check fails it says "API offline. Try again in a minute." rather than a developer message with the API's address; the failed request is in the browser console. It gives up after 10 seconds, so a hung API or a slow cold start on the hosted demo cannot leave it on "Checking the API…". It uses a timer rather than `AbortSignal.timeout` or `AbortSignal.any`, which older browsers lack.

**A styled "Page not found" page.** `src/app/not-found.tsx` replaces Next.js's default 404, which brought its own white background, system font and full-height block into our layout. Until stall pages exist, stall links land there.
