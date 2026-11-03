import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ApiError, apiBaseUrl, apiGet, apiPost, errorMessage, getStatus, type StatusReport } from "@/lib/api";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" }, ...init });
}

describe("apiBaseUrl", () => {
  it("defaults to the API on this machine", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", undefined);

    expect(apiBaseUrl()).toBe("http://localhost:8000");
  });

  it("uses NEXT_PUBLIC_API_BASE_URL, without a trailing slash", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example/");

    expect(apiBaseUrl()).toBe("https://api.example");
  });
});

describe("apiGet and apiPost", () => {
  let fetchMock: Mock<typeof fetch>;

  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
  });

  function sentRequest() {
    const [url, init] = fetchMock.mock.calls[0];
    return { url, method: init?.method, headers: new Headers(init?.headers), body: init?.body };
  }

  it("returns the JSON body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok" }));

    await expect(apiGet("/health")).resolves.toEqual({ status: "ok" });
    const request = sentRequest();
    expect(request.url).toBe("http://api.test/health");
    expect(request.method).toBe("GET");
    expect(request.headers.get("Accept")).toBe("application/json");
  });

  it("sends a JSON body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "ord_1" }, { status: 201 }));

    await expect(apiPost("/api/orders", { quantity: 40 })).resolves.toEqual({ id: "ord_1" });
    const request = sentRequest();
    expect(request.method).toBe("POST");
    expect(request.body).toBe('{"quantity":40}');
    expect(request.headers.get("Content-Type")).toBe("application/json");
  });

  it("returns nothing for 204 No Content", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiPost("/api/dev/reset", {})).resolves.toBeUndefined();
  });

  it("explains when the API cannot be reached", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await apiGet("/health").catch((thrown: unknown) => thrown);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: null,
      message: "Could not reach the OpenStall API at http://api.test. Check that it is running.",
    });
  });

  it("uses FastAPI's detail message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Order not found" }, { status: 404, statusText: "Not Found" }));

    await expect(apiGet("/api/orders/ord_x")).rejects.toMatchObject({
      status: 404,
      message: "Order not found (HTTP 404)",
    });
  });

  it("lists validation problems by field", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ["body", "quantity"], msg: "Input should be greater than 0", type: "greater_than" },
            { loc: ["body", "deadline"], msg: "Field required", type: "missing" },
          ],
        },
        { status: 422 },
      ),
    );

    await expect(apiPost("/api/quotes", { quantity: 0 })).rejects.toMatchObject({
      status: 422,
      message: "quantity: Input should be greater than 0; deadline: Field required (HTTP 422)",
    });
  });

  it("falls back to the HTTP status when the error has no JSON detail", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));

    await expect(apiGet("/health")).rejects.toMatchObject({
      status: 502,
      message: "The OpenStall API answered 502 Bad Gateway.",
    });
  });

  it("explains a reply that is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("not json", { status: 200 }));

    await expect(apiGet("/health")).rejects.toMatchObject({
      status: 200,
      message: "The OpenStall API sent a reply that is not JSON (/health).",
    });
  });

  it("keeps a cancelled call a cancellation, so callers can ignore it", async () => {
    const aborted = new DOMException("The operation was aborted.", "AbortError");
    fetchMock.mockRejectedValue(aborted);

    await expect(apiGet("/health")).rejects.toBe(aborted);
  });
});

describe("getStatus", () => {
  it("reads GET /api/status", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    const report: StatusReport = {
      mode: "fake",
      version: "0.1.0",
      database: { status: "ok", tables: { sellers: 0 }, message: null },
      payment: { status: "fake", path: "payouts", message: "Checkout runs on the simulated PayPal page." },
      commit: null,
      adapters: [],
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(report));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getStatus()).resolves.toEqual(report);
    expect(fetchMock).toHaveBeenCalledWith("http://api.test/api/status", expect.objectContaining({ method: "GET" }));
  });
});

describe("errorMessage", () => {
  it("uses the error's own message", () => {
    expect(errorMessage(new ApiError("Order not found (HTTP 404)", 404))).toBe("Order not found (HTTP 404)");
  });

  it("has a fallback for anything else", () => {
    expect(errorMessage("boom")).toBe("Something went wrong. Please try again.");
  });
});
