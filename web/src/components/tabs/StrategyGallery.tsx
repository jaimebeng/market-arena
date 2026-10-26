import { useState } from "react";
import type { GateStats, Run, TakerDecision } from "../../types";
import { fmtNum } from "../../lib/format";
import { useUi } from "../../lib/playback";
import { CodeBlock } from "../CodeBlock";
import { AgentName, ModelBadge } from "../ModelBadge";

const GATE_METRICS: { key: keyof GateStats; label: string; digits: number }[] = [
  { key: "pnl", label: "P&L", digits: 0 },
  { key: "sharpe", label: "Sharpe", digits: 2 },
  { key: "ic", label: "Rank-IC", digits: 3 },
  { key: "turnover", label: "turnover", digits: 2 },
];

const pretty = (s: string) => s.replace(/_/g, " ");

/** "≈ rediscovered X (ρ=0.81)" from the correlation with textbook signals. */
export function rediscovered(d: TakerDecision): { name: string; rho: number } | null {
  const e = Object.entries(d.similar_to ?? {});
  if (!e.length) return null;
  e.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const [name, rho] = e[0];
  return Math.abs(rho) >= 0.5 ? { name, rho } : null;
}

/** In-sample vs holdout bars, one row per metric, scaled per metric. */
export function GateBars({ d }: { d: TakerDecision }) {
  const ins = d.gate?.insample ?? {};
  const hold = d.gate?.holdout ?? {};
  return (
    <div className="gate-bars">
      <div className="gate-legend">
        <span>
          <i className="gb-in" /> in-sample
        </span>
        <span>
          <i className="gb-out" /> holdout
        </span>
      </div>
      {GATE_METRICS.map(({ key, label, digits }) => {
        const a = ins[key];
        const b = hold[key];
        if (a == null && b == null) return null;
        const m = Math.max(1e-9, Math.abs(a ?? 0), Math.abs(b ?? 0));
        const bar = (v: number | undefined, cls: string) => {
          const f = Math.abs(v ?? 0) / m;
          const neg = (v ?? 0) < 0;
          return (
            <div className="gb-row">
              <div className="gb-track">
                <i className="gb-zero" />
                <i
                  className={`gb-bar ${cls} ${neg ? "neg" : ""}`}
                  style={{ left: neg ? `${50 - f * 50}%` : "50%", width: `${f * 50}%` }}
                />
              </div>
              <span className={`mono gb-val ${neg ? "neg" : ""}`}>{fmtNum(v, digits)}</span>
            </div>
          );
        };
        return (
          <div className="gb-metric" key={key}>
            <label>{label}</label>
            <div>
              {bar(a, "gb-in")}
              {bar(b, "gb-out")}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function StrategyCard({ run, d, fresh }: { run: Run; d: TakerDecision; fresh?: boolean }) {
  const agent = run.agentById[d.agent];
  const passed = !!d.gate?.passed;
  const re = rediscovered(d);
  return (
    <article className={`strategy-card ${passed ? "pass" : "fail"} ${fresh ? "fresh" : ""}`} style={{ ["--agent" as string]: agent?.color }}>
      <header>
        <div className="sc-title">
          <span className="mono sc-name">{d.name}()</span>
          <div className="sc-sub">
            {agent && <AgentName agent={agent} />}
            {agent && <ModelBadge agent={agent} compact />}
            <span className="muted">epoch {d.epoch}</span>
          </div>
        </div>
        <div className={`stamp ${passed ? "pass" : "fail"}`}>{passed ? "PASS" : "FAIL"}</div>
      </header>
      {re && (
        <div className="rediscovered">
          ≈ rediscovered <b>{pretty(re.name)}</b> <span className="mono">(ρ={re.rho.toFixed(2)})</span>
        </div>
      )}
      <blockquote className="hypothesis">{d.hypothesis}</blockquote>
      <CodeBlock code={d.code ?? ""} maxLines={12} />
      {d.gate && <GateBars d={d} />}
      {d.gate?.reason && <div className={`gate-reason ${passed ? "pass" : "fail"}`}>{d.gate.reason}</div>}
      {d.live && <div className="live-chip">LIVE · trading with capital</div>}
    </article>
  );
}

export function StrategyGallery({ run }: { run: Run }) {
  const pb = useUi();
  const [showAll, setShowAll] = useState(false);
  const all = run.decisions.filter((d): d is TakerDecision => d.role === "taker");
  if (!all.length) {
    return (
      <div className="empty">
        <div className="empty-title">No taker strategies in this run</div>
        <p>
          Takers write their own trading strategy as Python code. Each submission is replayed on a hidden holdout and only
          trades if it passes the out-of-sample gate (Rank-IC ≥ 0.03 and positive net P&amp;L). Submissions land here with
          their hypothesis, code, in-sample vs holdout results and the textbook signal they resemble.
        </p>
        <p className="muted">Pick a run with takers (e.g. the fixture run) to see the gallery.</p>
      </div>
    );
  }
  const shown = (showAll ? all : all.filter((d) => d.t <= pb.t)).slice().reverse();
  const hidden = all.length - all.filter((d) => d.t <= pb.t).length;
  const passN = shown.filter((d) => d.gate?.passed).length;
  const latestT = shown[0]?.t;
  return (
    <div>
      <div className="tab-toolbar">
        <span>
          <b>{shown.length}</b> submissions · <b className="pass-c">{passN}</b> passed ·{" "}
          <b className="fail-c">{shown.length - passN}</b> rejected by the holdout gate
        </span>
        <span className="spacer" />
        {hidden > 0 && !showAll && <span className="muted">{hidden} more later in the replay</span>}
        <button className={`toggle ${showAll ? "on" : ""}`} onClick={() => setShowAll(!showAll)}>
          show all
        </button>
      </div>
      {shown.length === 0 ? (
        <div className="empty small">The first strategies arrive at the end of epoch 0.</div>
      ) : (
        <div className="gallery">
          {shown.map((d) => (
            <StrategyCard key={`${d.agent}-${d.t}`} run={run} d={d} fresh={!showAll && d.t === latestT && pb.t - d.t < run.config.steps_per_epoch / 2} />
          ))}
        </div>
      )}
    </div>
  );
}
