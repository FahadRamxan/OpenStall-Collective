import { afterEach, describe, expect, it, vi } from "vitest";

import { catalogEntryUrl, catalogUrl, llmsTxtUrl, mcpUrl, trustCardUrl } from "@/lib/agent-urls";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("agent URLs", () => {
  it("are on the API's public address", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.openstall.example/");

    expect(mcpUrl()).toBe("https://api.openstall.example/mcp");
    expect(catalogUrl()).toBe("https://api.openstall.example/catalog.json");
    expect(catalogEntryUrl("p_noor_cushion")).toBe("https://api.openstall.example/catalog/p_noor_cushion.json");
    expect(trustCardUrl("s_noor")).toBe("https://api.openstall.example/passport/s_noor");
    expect(llmsTxtUrl()).toBe("https://api.openstall.example/llms.txt");
  });

  it("escape the ids they are given", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");

    expect(catalogEntryUrl("p x/../y")).toBe("http://api.test/catalog/p%20x%2F..%2Fy.json");
    expect(trustCardUrl("s?x#y")).toBe("http://api.test/passport/s%3Fx%23y");
  });
});
