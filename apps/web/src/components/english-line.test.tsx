import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EnglishLine } from "@/components/english-line";

describe("EnglishLine", () => {
  it("says it is the English, in English, left to right, keeping the message's lines", () => {
    render(<EnglishLine text={"Hello Amina! You have a new order from OpenStall.\n\nOrder: ord_demo"} />);

    expect(screen.getByText("In English")).toBeInTheDocument();
    const words = screen.getByText(/Hello Amina! You have a new order from OpenStall/);
    expect(words).toHaveAttribute("lang", "en");
    expect(words).toHaveAttribute("dir", "ltr");
    expect(words).toHaveClass("whitespace-pre-line");
  });
});
