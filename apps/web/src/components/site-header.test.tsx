import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SiteHeader } from "@/components/site-header";
import { isCurrentPath, NavLinks } from "@/components/site-nav";

const navigation = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

function mainNavLinks() {
  return within(screen.getByRole("navigation", { name: "Main" })).getAllByRole("link");
}

describe("SiteHeader", () => {
  beforeEach(() => {
    navigation.pathname = "/";
  });

  it("links the OpenStall name to the home page", () => {
    render(<SiteHeader />);

    expect(screen.getByRole("link", { name: "OpenStall Collective" })).toHaveAttribute("href", "/");
  });

  it("links to Home, Demo, Seller chat and Dashboard, in that order", () => {
    render(<SiteHeader />);

    expect(mainNavLinks().map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Home", "/"],
      ["Demo", "/demo"],
      ["Seller chat", "/seller-chat"],
      ["Dashboard", "/dashboard"],
    ]);
  });

  it("marks only the current page", () => {
    navigation.pathname = "/seller-chat";
    render(<SiteHeader />);

    const current = mainNavLinks().filter((link) => link.getAttribute("aria-current") === "page");
    expect(current.map((link) => link.textContent)).toEqual(["Seller chat"]);
  });

  it("marks a section on the pages below it, and Home only on the home page", () => {
    navigation.pathname = "/dashboard/orders";
    render(<SiteHeader />);

    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });
});

describe("NavLinks", () => {
  it("marks no page while the current page is not known", () => {
    render(<NavLinks currentPath={null} />);

    for (const link of mainNavLinks()) {
      expect(link).not.toHaveAttribute("aria-current");
    }
  });
});

describe("isCurrentPath", () => {
  it.each([
    ["/", "/", true],
    ["/", "/demo", false],
    ["/demo", "/demo", true],
    ["/demo", "/demo/step-2", true],
    ["/demo", "/demonstration", false],
    ["/demo", null, false],
  ])("isCurrentPath(%j, %j) is %j", (href, pathname, expected) => {
    expect(isCurrentPath(href, pathname)).toBe(expected);
  });
});
