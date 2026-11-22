// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api/aid_wizard.js";
import Step1Year from "./Step1Year.jsx";
import Step2Buckets from "./Step2Buckets.jsx";
import Step3Awards from "./Step3Awards.jsx";
import Step4Preview from "./Step4Preview.jsx";
import Step5Commit from "./Step5Commit.jsx";
import Step6Verify from "./Step6Verify.jsx";

const STEPS = ["Aid Year", "Aid Buckets", "Stage Awards", "Preview", "Commit", "Verify"];
const CONTEXT = { sessionId: "synthetic-session", aidYear: "2026-2027", buckets: ["need"], awards: [] };
const props = (context = CONTEXT) => ({
  context, setContext: vi.fn(), goNext: vi.fn(), goPrev: vi.fn(),
  setStepIndex: vi.fn(), stepIndex: 0, totalSteps: 6, steps: STEPS,
});
afterEach(() => cleanup());

describe("CROWN officer wizard reused safely in standalone Jireh", () => {
  it("denies all six financial-aid server operations", async () => {
    for (const f of [
      api.createAidWizardSession, api.configureAidWizardSession,
      api.saveAidBuckets, api.stageAidAwards, api.commitAidSetup, api.verifyAidSetup,
    ]) {
      await expect(f()).rejects.toThrow(/disabled until authorized server integration/i);
    }
  });

  it("preserves all six original screen headings", () => {
    const comps = [Step1Year, Step2Buckets, Step3Awards, Step4Preview, Step5Commit, Step6Verify];
    const labels = [/Aid Year/, /Aid Buckets/, /Stage Awards/, /Preview/, /Commit Aid Setup/, /Verify/];
    for (let i = 0; i < comps.length; i++) {
      const Component = comps[i];
      const { unmount } = render(<Component {...props()} stepIndex={i} />);
      expect(screen.getByRole("heading", { name: labels[i] })).toBeTruthy();
      unmount();
    }
  });

  it("blocks year changes without the independent API", async () => {
    const p = props({ aidYear: "" });
    render(<Step1Year {...p} />);
    fireEvent.change(screen.getByPlaceholderText("e.g. 2026-2027"), {
      target: { value: "2026-2027" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect((await screen.findByText(/disabled until authorized server integration/i))).toBeTruthy();
    expect(p.goNext).not.toHaveBeenCalled();
  });

  it("blocks aid bucket saves without the independent API", async () => {
    const p = props();
    render(<Step2Buckets {...p} stepIndex={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect((await screen.findByText(/disabled until authorized server integration/i))).toBeTruthy();
    expect(p.goNext).not.toHaveBeenCalled();
  });

  it("keeps partial award rows invalid", () => {
    const p = props();
    render(<Step3Awards {...p} stepIndex={2} />);
    fireEvent.change(screen.getByPlaceholderText("UUID of the student receiving this award"), {
      target: { value: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Award #1:.*application ID/);
    expect(p.goNext).not.toHaveBeenCalled();
  });

  it("rejects a legacy numeric CROWN application identifier", () => {
    const p = props();
    render(<Step3Awards {...p} stepIndex={2} />);
    fireEvent.change(screen.getByPlaceholderText("Standalone Jireh application UUID"), {
      target: { value: "7" },
    });
    fireEvent.change(screen.getByPlaceholderText("UUID of the student receiving this award"), {
      target: { value: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
    });
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "250.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert").textContent).toMatch(/valid standalone application UUID/);
    expect(p.goNext).not.toHaveBeenCalled();
  });

  it("denies a no-awards skip until server integration is approved", async () => {
    const p = props();
    render(<Step3Awards {...p} stepIndex={2} />);
    fireEvent.click(screen.getByRole("button", { name: /No Awards/ }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/disabled until authorized server integration/i);
    expect(p.goNext).not.toHaveBeenCalled();
  });

  it("preserves the original zero-award preview", () => {
    render(<Step4Preview {...props()} stepIndex={3} />);
    expect(screen.getByText(/No awards staged/)).toBeTruthy();
    expect(screen.getByText("Total Staged Offer Amount")).toBeTruthy();
  });

  it("cannot commit even after confirmation", async () => {
    const p = props();
    render(<Step5Commit {...p} stepIndex={4} />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Commit Aid Setup" }));
    expect((await screen.findByText(/disabled until authorized server integration/i))).toBeTruthy();
    expect(p.goNext).not.toHaveBeenCalled();
  });

  it("cannot falsely verify a disabled award session", async () => {
    render(<Step6Verify {...props()} stepIndex={5} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/disabled until authorized server integration/i);
    expect(screen.queryByText(/Financial aid setup complete!/)).toBeNull();
  });
});
