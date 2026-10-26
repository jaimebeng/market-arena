import type { AgentView, ModelKind } from "../types";
import { MODEL_LABEL, modelTooltip } from "../lib/agents";

function Glyph({ kind }: { kind: ModelKind }) {
  switch (kind) {
    case "spark":
      return (
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden>
          <path d="M6 0.5 L7.2 4.8 L11.5 6 L7.2 7.2 L6 11.5 L4.8 7.2 L0.5 6 L4.8 4.8 Z" fill="currentColor" />
        </svg>
      );
    case "spark_open":
      return (
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden>
          <path d="M6 1.2 L7 5 L10.8 6 L7 7 L6 10.8 L5 7 L1.2 6 L5 5 Z" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
      );
    case "glft":
      return (
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden>
          <path d="M1 10 Q4 10 6 6 T11 2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden>
          <rect x="2" y="2" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
        </svg>
      );
  }
}

export function ModelBadge({ agent, kind, compact }: { agent?: AgentView; kind?: ModelKind; compact?: boolean }) {
  const k = agent?.kind ?? kind ?? "other";
  const label = agent?.modelLabel ?? MODEL_LABEL[k];
  return (
    <span className={`badge badge-${k} ${compact ? "compact" : ""}`} title={agent ? modelTooltip(agent) : label}>
      <Glyph kind={k} />
      {label}
    </span>
  );
}

export function RoleTag({ role }: { role: string }) {
  return <span className={`role-tag role-${role}`}>{role}</span>;
}

export function AgentName({ agent }: { agent: AgentView }) {
  return (
    <span className="agent-name">
      <i className="agent-dot" style={{ background: agent.color, boxShadow: `0 0 8px ${agent.color}` }} />
      {agent.id}
    </span>
  );
}
