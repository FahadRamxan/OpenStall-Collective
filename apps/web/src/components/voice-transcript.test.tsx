import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VoiceTranscript } from "@/components/voice-transcript";

const URDU = "کڑھائی والے کشن کور، تین رنگوں میں";

describe("VoiceTranscript", () => {
  it("shows her words as she said them, marked with their language so they read right to left", () => {
    render(<VoiceTranscript text={URDU} language="ur" />);

    expect(screen.getByText("Voice note in Urdu, as text")).toBeInTheDocument();
    const words = screen.getByText(URDU);
    expect(words.tagName).toBe("BLOCKQUOTE");
    expect(words).toHaveAttribute("lang", "ur");
    expect(words).toHaveAttribute("dir", "auto");
  });

  it("without a language, says only that it is a voice note and claims no language", () => {
    render(<VoiceTranscript text="Fifteen a week" language={null} />);

    expect(screen.getByText("Voice note, as text")).toBeInTheDocument();
    expect(screen.getByText("Fifteen a week")).not.toHaveAttribute("lang");
  });
});
