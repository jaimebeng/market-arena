import type { AgentInfo, AgentView, ModelKind } from "../types";

// One palette per model family so colour alone says "which model" at a glance.
const PALETTE: Record<ModelKind, string[]> = {
  spark: ["#7b8cff", "#b18cff", "#5fb4ff", "#c4a1ff", "#6f9dff", "#d59cff"],
  spark_open: ["#2dd4bf", "#7ee081", "#38d0f0", "#a3e635", "#5eead4", "#4ade80"],
  glft: ["#f5b841", "#f59e0b"],
  scripted: ["#f472b6", "#fb923c", "#a3a9b8", "#e879f9"],
  other: ["#e2e8f0", "#fca5a5", "#c4b5fd"],
};

export const MODEL_LABEL: Record<ModelKind, string> = {
  spark: "Muse Spark",
  spark_open: "Muse Spark Open",
  glft: "GLFT benchmark",
  scripted: "Scripted",
  other: "Model",
};

export const BUY = "#34d399";
export const SELL = "#f87171";
export const BUY_RGB: [number, number, number] = [52, 211, 153];
export const SELL_RGB: [number, number, number] = [248, 113, 113];
export const ASSET_COLORS = ["#e5e7eb", "#93c5fd", "#fde68a", "#c4b5fd", "#fca5a5"];

/** The AI surveillance officer gets one fixed colour of its own (it never trades). */
export const REGULATOR_COLOR = "#fde047";

/** Non-LLM agents described by a "scripted: …" / "textbook: …" model string. */
const SCRIPTED_MODEL = /^(scripted|textbook)\s*:/i;

export function modelKind(a: AgentInfo): ModelKind {
  const m = (a.model ?? "").toLowerCase();
  if (a.id === "glft" || m.includes("glft")) return "glft";
  if (m.includes("spark-open") || m.includes("spark_open")) return "spark_open";
  if (m.includes("spark")) return "spark";
  if (!a.model || SCRIPTED_MODEL.test(a.model)) return "scripted";
  return "other";
}

export function buildAgentViews(agents: AgentInfo[]): AgentView[] {
  const used: Record<string, number> = {};
  return agents.map((a, index) => {
    const kind = modelKind(a);
    const regulator = a.role === "regulator";
    const k = used[kind] ?? 0;
    if (!regulator) used[kind] = k + 1;
    const pal = PALETTE[kind];
    return {
      ...a,
      index,
      kind,
      modelLabel: kind === "other" || (a.model && SCRIPTED_MODEL.test(a.model)) ? (a.model ?? "Model") : MODEL_LABEL[kind],
      color: regulator ? REGULATOR_COLOR : pal[k % pal.length],
      isLLM: kind === "spark" || kind === "spark_open" || kind === "other",
    };
  });
}

export function modelTooltip(a: AgentView): string {
  return a.model ? `${a.modelLabel} · ${a.model}` : a.modelLabel;
}
