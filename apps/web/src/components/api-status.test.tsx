import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiStatus, HEALTH_CHECK_TIMEOUT_MS } from "@/components/api-status";

const OFFLINE = "API offline. Try again in a minute.";

/** A fetch that never answers, like a hung API, but rejects when its call is aborted, as fetch does. */
function hangingFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
      }),
  );
}

describe("ApiStatus", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("says the API is online when /health answers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ApiStatus />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking the API…");
    expect(await screen.findByText("API online")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://api.test/health", expect.objectContaining({ method: "GET" }));
  });

  it("says the API is offline, in words for visitors, when it cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<ApiStatus />);

    const status = await screen.findByText(OFFLINE);
    // Visitors see the footer too: no API address and no instructions meant for developers.
    expect(status).not.toHaveTextContent("http://api.test");
    expect(status).not.toHaveTextContent(/check that it is running/i);
  });

  it("says the API is offline when it answers with an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Service Unavailable", { status: 503 })));

    render(<ApiStatus />);

    expect(await screen.findByText(OFFLINE)).toBeInTheDocument();
  });

  it("gives up after 10 seconds, so a hung API cannot leave it checking", async () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<ApiStatus />);
    await act(() => vi.advanceTimersByTimeAsync(HEALTH_CHECK_TIMEOUT_MS - 1));
    expect(screen.getByRole("status")).toHaveTextContent("Checking the API…");

    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByRole("status")).toHaveTextContent(OFFLINE);
    expect(HEALTH_CHECK_TIMEOUT_MS).toBe(10_000);
  });

  it("stops checking when it is removed from the page", async () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = render(<ApiStatus />);
    unmount();

    const { signal } = fetchMock.mock.calls[0][1] as RequestInit;
    expect(signal?.aborted).toBe(true);
    // Its timer is gone too, so nothing fires after it has left the page.
    expect(vi.getTimerCount()).toBe(0);
  });
});
