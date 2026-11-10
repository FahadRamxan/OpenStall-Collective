import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Confetti } from "@/components/confetti";

function prefersLessMotion(reduced: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduced && query.includes("reduce"),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("Confetti", () => {
  it("bursts once, hidden from screen readers, and never takes a click", () => {
    prefersLessMotion(false);

    const { container } = render(<Confetti />);

    const burst = container.firstElementChild;
    expect(burst).toHaveAttribute("aria-hidden", "true");
    expect(burst).toHaveClass("pointer-events-none");
    expect(burst?.children).toHaveLength(42);
  });

  it("shows nothing to someone who asks for less motion", () => {
    prefersLessMotion(true);

    const { container } = render(<Confetti />);

    expect(container).toBeEmptyDOMElement();
  });
});
