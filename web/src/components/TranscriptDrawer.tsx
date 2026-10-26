import { useEffect, useRef } from "react";
import type { AgentView, Decision, MakerPolicy, Run, ToolCall } from "../types";
import { fmtCompact, fmtNum, fmtUsd } from "../lib/format";
import { useUi } from "../lib/playback";
import { latestDecision, policyAt } from "../lib/query";
import { AgentName, ModelBadge, RoleTag } from "./ModelBadge";
import { CodeBlock } from "./CodeBlock";
import { GateBars, rediscovered } from "./tabs/StrategyGallery";

function Json({ value }: { value: unknown }) {
  const s = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="json">{s}</pre>;
}

function argsInline(args: unknown): string {
  if (args == null) return "";
  if (typeof args !== "object") return String(args);
  const e = Object.entries(args as Record<string, unknown>);
  return e
    .map(([k, v]) => {
      let s = typeof v === "string" ? JSON.stringify(v) : JSON.stringify(v);
      if (s && s.length > 40) s = s.slice(0, 37) + "…";
      return `${k}=${s}`;
    })
    .join(", ");
}

function Call({ c }: { c: ToolCall }) {
  return (
    <details className={`call ${c.ok ? "ok" : "err"}`}>
      <summary>
        <span className={`call-status ${c.ok ? "ok" : "err"}`}>{c.ok ? "✓" : "✗"}</span>
        <span className="mono call-name">{c.name}</span>
        <span className="mono call-args">({argsInline(c.args)})</span>
      </summary>
      <div className="call-body">
        <div className="call-label">args</div>
        <Json value={c.args} />
        <div className="call-label">result</div>
        <Json value={c.result} />
      </div>
    </details>
  );
}

function PolicyDiff({ before, after }: { before?: Record<string, MakerPolicy>; after: Record<string, MakerPolicy> }) {
  const keys = ["half_spread", "skew", "size", "max_inventory", "requote_every"];
  return (
    <table className="policy-diff">
      <thead>
        <tr>
          <th />
          {keys.map((k) => (
            <th key={k}>{k.replace("_", " ")}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Object.entries(after).map(([asset, p]) => (
          <tr key={asset}>
            <td className="muted">{asset}</td>
            {keys.map((k) => {
              const a = before?.[asset]?.[k] as number | undefined;
              const b = p[k] as number | undefined;
              const changed = a != null && b != null && Math.abs(a - b) > 1e-9;
              return (
                <td key={k} className="mono">
                  {changed && <span className="was">{fmtNum(a, k.includes("spread") || k === "skew" ? 2 : 0)} → </span>}
                  <span className={changed ? (b! > a! ? "up" : "down") : ""}>{fmtNum(b, k.includes("spread") || k === "skew" ? 2 : 0)}</span>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DecisionView({ run, d, current }: { run: Run; d: Decision; current: boolean }) {
  const tok = d.tokens ?? {};
  return (
    <section className={`decision ${current ? "current" : ""}`} id={`dec-${d.agent}-${d.t}`}>
      <header className="decision-head">
        <span className="decision-epoch">Epoch {d.epoch} review</span>
        <span className="muted mono">t={d.t.toLocaleString("en-US")}</span>
        {d.role === "taker" && <span className={`gate-chip ${d.gate?.passed ? "pass" : "fail"}`}>{d.gate?.passed ? "PASS" : "FAIL"}</span>}
        <span className="spacer" />
        <span className="muted mono small">
          {d.seconds != null && `${d.seconds.toFixed(1)}s · `}
          {fmtCompact((tok.in ?? 0) + (tok.out ?? 0))} tok
          {tok.reasoning ? ` (${fmtCompact(tok.reasoning)} reasoning)` : ""} · {fmtUsd(d.cost)}
        </span>
      </header>
      {d.error && <div className="bubble-error">error: {d.error}</div>}

      {d.role === "maker" ? (
        <>
          <div className="block-label">rationale (public)</div>
          <blockquote className="rationale">{d.rationale}</blockquote>
          <div className="block-label">new policy · applies from epoch {d.epoch + 1}</div>
          <PolicyDiff before={policyAt(run, d.agent, d.t - 1)} after={d.policy} />
        </>
      ) : (
        <>
          <div className="block-label">
            hypothesis · <span className="mono">{d.name}()</span>
            {(() => {
              const re = rediscovered(d);
              return re ? <span className="rediscovered inline"> ≈ {re.name.replace(/_/g, " ")} (ρ={re.rho.toFixed(2)})</span> : null;
            })()}
          </div>
          <blockquote className="rationale">{d.hypothesis}</blockquote>
          <CodeBlock code={d.code ?? ""} maxLines={30} />
          {d.gate && <GateBars d={d} />}
          {d.gate?.reason && <div className={`gate-reason ${d.gate.passed ? "pass" : "fail"}`}>{d.gate.reason}</div>}
        </>
      )}
      {d.notes && (
        <>
          <div className="block-label">private notebook</div>
          <div className="notes">{d.notes}</div>
        </>
      )}

      {d.turns && d.turns.length > 0 && (
        <>
          <div className="block-label">transcript · {d.turns.length} turns</div>
          <ol className="turns">
            {d.turns.map((turn, i) => (
              <li key={i} className="turn">
                <div className="turn-n mono">{i + 1}</div>
                <div className="turn-body">
                  {turn.reasoning && (
                    <details className="reasoning">
                      <summary>reasoning</summary>
                      <div>{turn.reasoning.trim()}</div>
                    </details>
                  )}
                  {turn.text && <p className="turn-text">{turn.text}</p>}
                  {turn.calls.map((c, j) => (
                    <Call key={j} c={c} />
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

export function TranscriptDrawer({ run, agent, onClose }: { run: Run; agent: AgentView; onClose: () => void }) {
  const pb = useUi((p) => latestDecision(run, agent.id, p.t)?.t ?? -1);
  const ds = run.decisionsByAgent[agent.id] ?? [];
  const cur = latestDecision(run, agent.id, pb.t);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!cur) return;
    body.current?.querySelector(`#dec-${CSS.escape(cur.agent)}-${cur.t}`)?.scrollIntoView({ block: "start" });
    // only when the drawer opens / agent changes
  }, [agent.id]);

  const cost = ds.reduce((s, d) => s + (d.cost ?? 0), 0);
  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer" style={{ ["--agent" as string]: agent.color }} onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <AgentName agent={agent} />
          <RoleTag role={agent.role} />
          <ModelBadge agent={agent} />
          <span className="spacer" />
          <button className="icon-btn" onClick={onClose} title="Close (Esc)">
            ✕
          </button>
        </header>
        <div className="drawer-sub muted">
          {agent.model ?? "no model"} · {ds.length} reviews · {fmtUsd(cost)}
        </div>
        <div className="drawer-body" ref={body}>
          {ds.length === 0 ? (
            <div className="empty small">This agent does not review (no LLM).</div>
          ) : (
            ds.map((d) => <DecisionView key={d.t} run={run} d={d} current={d === cur} />)
          )}
        </div>
      </aside>
    </div>
  );
}
