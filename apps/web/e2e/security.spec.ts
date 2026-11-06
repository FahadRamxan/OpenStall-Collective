import { expect, test } from "@playwright/test";

import { E2E_API_URL } from "../playwright.config";

// Security headers (prompt 46): every page and every API answer says no framing by other sites and no type guessing;
// pages also send the address to other sites only as far as the origin, and allow no camera or location (the
// microphone only on the site itself, for a seller's voice notes).

test("every page says no framing, no type guessing, and no camera or location", async ({ request }) => {
  for (const path of ["/", "/demo", "/status", "/seller-chat"]) {
    const headers = (await request.get(path)).headers();
    expect(headers["x-frame-options"], path).toBe("DENY");
    expect(headers["x-content-type-options"], path).toBe("nosniff");
    expect(headers["referrer-policy"], path).toBe("strict-origin-when-cross-origin");
    expect(headers["permissions-policy"], path).toBe("camera=(), geolocation=(), microphone=(self)");
    expect(headers["content-security-policy"], path).toBe("frame-ancestors 'none'; base-uri 'self'; object-src 'none'");
  }
});

test("the API's answers say the same", async ({ request }) => {
  for (const path of ["/health", "/api/status", "/catalog.json"]) {
    const headers = (await request.get(`${E2E_API_URL}${path}`)).headers();
    expect(headers["x-frame-options"], path).toBe("DENY");
    expect(headers["x-content-type-options"], path).toBe("nosniff");
  }
});
