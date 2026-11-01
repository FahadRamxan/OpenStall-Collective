import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Every page must fit a 375px phone without sideways scrolling. Each run also saves full-page
// screenshots to e2e/screenshots/ (ignored by git) for a quick look at the layout.
const PAGES = ["/", "/demo", "/seller-chat", "/dashboard", "/status", "/stall/does-not-exist"];

// Pages that load data after the first paint: wait for it, so the checks and the screenshot see the whole page.
const LOADED: Record<string, (page: Page) => Promise<void>> = {
  "/status": (page) => expect(page.getByRole("table", { name: "Adapters" })).toBeVisible(),
};

const VIEWPORTS = [
  { width: 375, height: 812 },
  { width: 1280, height: 720 },
];
const SCREENSHOTS = path.join(__dirname, "screenshots");

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.width}px wide`, () => {
    test.use({ viewport });

    for (const pagePath of PAGES) {
      test(`${pagePath} fits the screen`, async ({ page }) => {
        await page.goto(pagePath);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
        // Let the footer's API check finish, so the screenshot shows its final state.
        await expect(page.getByRole("contentinfo").getByRole("status")).not.toHaveText(/Checking/);
        await LOADED[pagePath]?.(page);

        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0);

        const name = pagePath === "/" ? "home" : pagePath.slice(1).replaceAll("/", "-");
        await page.screenshot({ path: path.join(SCREENSHOTS, `${name}-${viewport.width}.png`), fullPage: true });
      });
    }
  });
}

// 44px is the usual minimum for something you tap; 320px is the narrowest screen pages must work on.
for (const width of [320, 375]) {
  test(`at ${width}px the header links are easy to tap and fit on one row`, async ({ page }) => {
    await page.setViewportSize({ width, height: 700 });
    await page.goto("/");

    const links = page.getByRole("navigation", { name: "Main" }).getByRole("link");
    await expect(links).toHaveCount(4);
    const boxes = await Promise.all((await links.all()).map((link) => link.boundingBox()));
    for (const box of boxes) {
      expect(box?.height, "link height").toBeGreaterThanOrEqual(44);
      expect(box?.y, "every link on the first row").toBe(boxes[0]?.y);
    }
  });
}
