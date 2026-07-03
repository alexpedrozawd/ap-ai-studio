import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BeforeAfterCompare from "./BeforeAfterCompare";

describe("BeforeAfterCompare", () => {
  it("mostra so' o resultado (sem 'Antes') quando nao ha arquivo original", () => {
    render(<BeforeAfterCompare originalFile={null} resultUrl="/api/jobs/abc/output" />);
    expect(screen.queryByText("Antes")).not.toBeInTheDocument();
    expect(screen.getByAltText("resultado")).toHaveAttribute("src", "/api/jobs/abc/output");
  });

  it("mostra antes e depois lado a lado quando ha um arquivo original (imagem)", () => {
    const original = new File(["a"], "original.jpg", { type: "image/jpeg" });
    render(<BeforeAfterCompare originalFile={original} resultUrl="/api/jobs/abc/output" />);
    expect(screen.getByText("Antes")).toBeInTheDocument();
    expect(screen.getByText("Depois")).toBeInTheDocument();
    expect(screen.getByAltText("antes")).toBeInTheDocument();
    expect(screen.getByAltText("resultado")).toHaveAttribute("src", "/api/jobs/abc/output");
  });

  it("usa <video> nos dois lados quando isVideo e' true", () => {
    const original = new File(["a"], "original.mp4", { type: "video/mp4" });
    const { container } = render(
      <BeforeAfterCompare originalFile={original} resultUrl="/api/jobs/abc/output" isVideo />,
    );
    expect(container.querySelectorAll("video")).toHaveLength(2);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("aceita rotulos customizados (ex.: 'Depois (4x)' do upscale)", () => {
    const original = new File(["a"], "original.jpg", { type: "image/jpeg" });
    render(
      <BeforeAfterCompare
        originalFile={original}
        resultUrl="/api/jobs/abc/output"
        afterLabel="Depois (4x)"
      />,
    );
    expect(screen.getByText("Depois (4x)")).toBeInTheDocument();
  });
});
