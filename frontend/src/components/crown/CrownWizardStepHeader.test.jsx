// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import CrownWizardStepHeader from "./CrownWizardStepHeader.jsx";

afterEach(() => cleanup());

describe("Existing CROWN wizard step header in standalone Jireh", () => {
  it("shows the correct current and completed steps without inventing financial states", () => {
    const { container } = render(
      <CrownWizardStepHeader
        title="Aid Year"
        subtitle="Configure the academic year"
        stepIndex={1}
        steps={["School", "Aid Year", "Review"]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Aid Year" })).toBeTruthy();
    expect(screen.getByText("Configure the academic year")).toBeTruthy();
    expect(container.querySelector(".crown-wizard-step-pill.done")?.textContent).toContain("School");
    expect(container.querySelector(".crown-wizard-step-pill.active")?.textContent).toContain("Aid Year");
    expect(container.querySelectorAll(".crown-wizard-step-pill")).toHaveLength(3);
  });
});
