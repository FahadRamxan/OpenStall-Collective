import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { COPIED_SHOWN_MS, CopyField } from "@/components/copy-field";

const MCP = "https://api.openstall.example/mcp";

/** jsdom has no Clipboard API: give the page one, or none (undefined), for one test. */
function useClipboard(clipboard: { writeText: (text: string) => Promise<void> } | undefined) {
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
}

async function clickCopy() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Copy the MCP server address" }));
  });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
  window.getSelection()?.removeAllRanges();
  vi.useRealTimers();
});

describe("CopyField", () => {
  it("shows the value under its label, with a Copy button", () => {
    render(<CopyField label="MCP server address" value={MCP} />);

    const group = screen.getByRole("group", { name: "MCP server address" });
    expect(within(group).getByText(MCP)).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Copy the MCP server address" })).toHaveTextContent("Copy");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("copies the value and says Copied where everyone, screen readers included, can see it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    useClipboard({ writeText });
    render(<CopyField label="MCP server address" value={MCP} />);

    await clickCopy();

    expect(writeText).toHaveBeenCalledWith(MCP);
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
  });

  it("says Copied again on a second copy, then clears it after a few seconds", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    useClipboard({ writeText });
    render(<CopyField label="MCP server address" value={MCP} />);

    await clickCopy();
    const first = screen.getByText("Copied");
    act(() => vi.advanceTimersByTime(COPIED_SHOWN_MS - 1));
    await clickCopy();

    // A new element, so screen readers read it out again; and the wait starts over from the second copy.
    expect(screen.getByText("Copied")).not.toBe(first);
    act(() => vi.advanceTimersByTime(COPIED_SHOWN_MS - 1));
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(writeText).toHaveBeenCalledTimes(2);
  });

  it("selects the value and says how to copy it, with a keyboard or on a phone, when the browser refuses", async () => {
    useClipboard({ writeText: vi.fn().mockRejectedValue(new DOMException("Not allowed", "NotAllowedError")) });
    render(<CopyField label="MCP server address" value={MCP} />);

    await clickCopy();

    expect(screen.getByRole("status")).toHaveTextContent(
      "This browser did not let the page copy, so the text is selected: press Ctrl+C (⌘C on a Mac) to copy it, or " +
        "on a phone, press and hold it, then choose Copy.",
    );
    expect(window.getSelection()?.toString()).toBe(MCP);
  });

  it("does the same where there is no Clipboard API at all", async () => {
    useClipboard(undefined);
    render(<CopyField label="MCP server address" value={MCP} />);

    await clickCopy();

    expect(screen.getByRole("status")).toHaveTextContent("did not let the page copy");
    expect(screen.getByRole("status")).toHaveTextContent("on a phone, press and hold it, then choose Copy.");
    expect(window.getSelection()?.toString()).toBe(MCP);
  });
});
