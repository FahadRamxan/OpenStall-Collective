import { act, render, screen, within } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatComposer } from "@/components/chat-composer";

/** A browser that can record. jsdom has neither MediaRecorder nor navigator.mediaDevices. */
function giveTheBrowserAMicrophone() {
  vi.stubGlobal("MediaRecorder", class {});
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn() }, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
  document.body.innerHTML = "";
});

describe("ChatComposer", () => {
  it("with a microphone, offers to record a voice note", () => {
    giveTheBrowserAMicrophone();

    render(<ChatComposer onSend={vi.fn()} busy={false} />);

    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Upload a voice note")).not.toBeInTheDocument();
  });

  it("hydrates the server's page without a mismatch, then offers to record", async () => {
    // The server cannot know about the microphone, so its page offers an upload. Deciding during the browser's first
    // render made that render differ from the server's HTML, and React threw the HTML away (a hydration error).
    const html = renderToString(<ChatComposer onSend={vi.fn()} busy={false} />);
    expect(html).toContain("Upload a voice note");
    giveTheBrowserAMicrophone();
    const container = document.createElement("div");
    container.innerHTML = html;
    document.body.append(container);
    const onRecoverableError = vi.fn();

    await act(async () => {
      hydrateRoot(container, <ChatComposer onSend={vi.fn()} busy={false} />, { onRecoverableError });
    });

    expect(onRecoverableError).not.toHaveBeenCalled();
    expect(within(container).getByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
  });
});
