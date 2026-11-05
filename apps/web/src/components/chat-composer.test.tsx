import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatComposer } from "@/components/chat-composer";

const SAMPLE = "/api/dev/samples/voice-note.wav";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

/** A browser that can record. jsdom has neither MediaRecorder nor navigator.mediaDevices. */
function giveTheBrowserAMicrophone() {
  vi.stubGlobal("MediaRecorder", class {});
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn() }, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  Reflect.deleteProperty(navigator, "mediaDevices");
  document.body.innerHTML = "";
});

describe("ChatComposer, the sample voice note (test mode)", () => {
  it("attaches the sample as a voice note and sends it like any other", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("RIFF a made-up wav", { headers: { "Content-Type": "audio/wav" } }));
    vi.stubGlobal("fetch", fetch);
    const onSend = vi.fn().mockResolvedValue(true);
    render(<ChatComposer onSend={onSend} busy={false} sampleVoiceNote={SAMPLE} />);

    fireEvent.click(screen.getByRole("button", { name: /Attach the sample voice note/ }));

    expect(await screen.findByRole("button", { name: "Remove the voice note" })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(`http://api.test${SAMPLE}`);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    const [text, files] = onSend.mock.calls[0] as [string, File[]];
    expect(text).toBe("");
    expect(files.map((file) => [file.name, file.type])).toEqual([["sample-voice-note.wav", "audio/wav"]]);
  });

  it("says so when the sample cannot be loaded, and keeps everything else as it was", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("gone", { status: 404 })));
    render(<ChatComposer onSend={vi.fn()} busy={false} sampleVoiceNote={SAMPLE} />);

    fireEvent.click(screen.getByRole("button", { name: /Attach the sample voice note/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The sample voice note could not be attached");
    expect(screen.queryByRole("list", { name: "Attached" })).not.toBeInTheDocument();
  });

  it("outside test mode there is no sample to attach", () => {
    render(<ChatComposer onSend={vi.fn()} busy={false} sampleVoiceNote={null} />);

    expect(screen.queryByRole("button", { name: /sample voice note/ })).not.toBeInTheDocument();
  });
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
