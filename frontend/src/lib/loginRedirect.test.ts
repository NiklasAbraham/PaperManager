import { describe, it, expect, beforeEach } from "vitest";
import { rememberReturnTo, takeReturnTo } from "./loginRedirect";

describe("loginRedirect", () => {
  beforeEach(() => sessionStorage.clear());

  it("prefers router state, then storage, then home", () => {
    rememberReturnTo("/paper/abc");
    expect(takeReturnTo("/paper/xyz?tab=notes")).toBe("/paper/xyz?tab=notes");
    rememberReturnTo("/paper/abc#h");
    expect(takeReturnTo()).toBe("/paper/abc#h");
    expect(takeReturnTo()).toBe("/");
  });

  it("rejects login and external targets", () => {
    expect(takeReturnTo("/login")).toBe("/");
    expect(takeReturnTo("//evil.com")).toBe("/");
    expect(takeReturnTo("https://evil.com")).toBe("/");
  });
});
