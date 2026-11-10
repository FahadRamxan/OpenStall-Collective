import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FormattedText } from "@/components/formatted-text";
import { ReplyButtons } from "@/components/reply-buttons";

describe("FormattedText", () => {
  it("shows WhatsApp's *bold* in bold and leaves the rest as written", () => {
    const { container } = render(
      <p>
        <FormattedText text={"*OpenStall میں خوش آمدید!*\n\n1. اپنے ہاتھ سے بنی چیز کی تصویر بھیجیں۔ 2 * 3 = 6"} />
      </p>,
    );

    expect(screen.getByText("OpenStall میں خوش آمدید!").tagName).toBe("STRONG");
    expect(container.querySelectorAll("strong")).toHaveLength(1);
    expect(container.textContent).toContain("1. اپنے ہاتھ سے بنی چیز کی تصویر بھیجیں۔ 2 * 3 = 6");
    expect(container.textContent).not.toContain("*OpenStall");
  });
});

describe("ReplyButtons", () => {
  it("on her own phone, a tap sends the button's title", () => {
    const choose = vi.fn();
    render(<ReplyButtons titles={["ہاں، اشتہار لگائیں"]} onChoose={choose} />);

    screen.getByRole("button", { name: "ہاں، اشتہار لگائیں" }).click();

    expect(choose).toHaveBeenCalledWith("ہاں، اشتہار لگائیں");
    expect(screen.getByRole("group", { name: "Answer with a button" })).toBeInTheDocument();
  });

  it("watching her chat, the buttons are shown as they look on her phone, not pressable", () => {
    render(<ReplyButtons titles={["Yes, drop my share", "No, I'll make it"]} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Buttons under this message on WhatsApp" })).toHaveTextContent(
      "Yes, drop my share",
    );
  });

  it("shows nothing for a message without buttons", () => {
    const { container } = render(<ReplyButtons titles={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
