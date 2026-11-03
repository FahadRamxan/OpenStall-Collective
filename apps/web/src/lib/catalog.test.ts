import { afterEach, describe, expect, it, vi } from "vitest";

import { formatUsd, getSeller, languageName, mediaUrl, percent, place, swatch } from "@/lib/catalog";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("catalog helpers", () => {
  it("formats exact prices as dollars", () => {
    expect(formatUsd("16.00")).toBe("$16.00");
    expect(formatUsd("28.5")).toBe("$28.50");
    expect(formatUsd("1234.00")).toBe("$1,234.00");
  });

  it("names places and languages in English", () => {
    expect(place("Jaipur", "IN")).toBe("Jaipur, India");
    expect(place("Lahore", "PK")).toBe("Lahore, Pakistan");
    expect(place("Oaxaca", null)).toBe("Oaxaca");
    expect(place(null, null)).toBeNull();
    expect(languageName("ur")).toBe("Urdu");
    expect(languageName("es")).toBe("Spanish");
    expect(languageName(null)).toBeNull();
  });

  it("shows rates as whole percentages", () => {
    expect(percent(0.97)).toBe("97%");
    expect(percent(0)).toBe("0%");
  });

  it("serves photo paths from the API and leaves full URLs alone", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");

    expect(mediaUrl("/media/seed/priya-cushion-1.svg")).toBe("http://api.test/media/seed/priya-cushion-1.svg");
    expect(mediaUrl("https://cdn.example/photo.jpg")).toBe("https://cdn.example/photo.jpg");
  });

  it("knows a swatch for the colours sellers use, and nothing for others", () => {
    expect(swatch("Indigo")).toBe("#2f3e7a");
    expect(swatch("ultraviolet")).toBeNull();
  });

  it("asks for one stall by its escaped id", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ id: "s_x" }));
    vi.stubGlobal("fetch", fetchMock);

    await getSeller("s x/../y");

    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/sellers/s%20x%2F..%2Fy");
  });
});
