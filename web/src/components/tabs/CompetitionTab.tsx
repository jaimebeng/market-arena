import type { Benchmarks, Run } from "../../types";
import { BUY, SELL } from "../../lib/agents";
import { clamp, fmtNum, fmtSigned } from "../../lib/format";
import { useUi } from "../../lib/playback";
import { completedMetrics, pnlAt } from "../../lib/query";
import { ChartLegend, EpochChart, type ChartSeries, type RefLine } from "../charts/EpochChart";
import { AgentName, ModelBadge } from "../ModelBadge";

const NASH = "#cbd5e1";
const PARETO = "#f87171";
const GLFT = "#f5b841";

/** Collusion index per epoch: logged value, or derived from benchmarks + LLM makers' quoted spreads. */
export function collusionSeries(run: Run, asset: string): { values: (number | null)[]; derived: boolean } {
  let derived = false;
  const values = run.metrics.map((m) => {
    const ci = m.collusion_index?.[asset];
    if (ci != null) return ci;
    const b = m.benchmarks?.[asset];
    if (!b || b.nash_hs == null || b.pareto_hs == null || b.pareto_hs === b.nash_hs) return null;
    const hs = run.makers
      .filter((a) => a.isLLM)
      .map((a) => m.agents[a.id]?.quoted_half_spread?.[asset] ?? m.policies?.[a.id]?.[asset]?.half_spread)
      .filter((x): x is number => x != null);
    if (!hs.length) return null;
    derived = true;
    const mean = hs.reduce((s, x) => s + x, 0) / hs.length;
    return (mean - b.nash_hs) / (b.pareto_hs - b.nash_hs);
  });
  return { values, derived };
}

function CollusionGauge({ value, history, derived }: { value: number | null; history: (number | null)[]; derived: boolean }) {
  const R = 78;
  const cx = 100;
  const cy = 92;
  const v = value == null ? 0 : clamp(value, -0.1, 1.1);
  const ang = Math.PI * (1 - clamp(v, 0, 1)); // 180° (Nash) → 0° (Pareto)
  const arc = (a0: number, a1: number) =>
    `M ${cx + R * Math.cos(a0)} ${cy - R * Math.sin(a0)} A ${R} ${R} 0 0 1 ${cx + R * Math.cos(a1)} ${cy - R * Math.sin(a1)}`;
  const label = value == null ? "—" : value < 0.2 ? "competitive" : value < 0.6 ? "drifting" : "collusive";
  return (
    <div className="gauge">
      <svg viewBox="0 0 200 116" width="100%">
        <defs>
          <linearGradient id="gauge-grad" x1="0" x2="1">
            <stop offset="0" stopColor="#2dd4bf" />
            <stop offset="0.5" stopColor="#f5b841" />
            <stop offset="1" stopColor="#f87171" />
          </linearGradient>
        </defs>
        <path d={arc(Math.PI, 0)} stroke="#1c2230" strokeWidth="14" fill="none" strokeLinecap="round" />
        <path d={arc(Math.PI, 0)} stroke="url(#gauge-grad)" strokeWidth="14" fill="none" strokeLinecap="round" opacity={value == null ? 0.25 : 0.9} />
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const a = Math.PI * (1 - f);
          return <line key={f} x1={cx + (R - 12) * Math.cos(a)} y1={cy - (R - 12) * Math.sin(a)} x2={cx + (R - 18) * Math.cos(a)} y2={cy - (R - 18) * Math.sin(a)} stroke="#4b5568" strokeWidth="1.5" />;
        })}
        {value != null && (
          <g className="needle" style={{ transform: `rotate(${(-ang * 180) / Math.PI}deg)`, transformOrigin: `${cx}px ${cy}px` }}>
            <line x1={cx} y1={cy} x2={cx + R - 22} y2={cy} stroke="#f3f4f6" strokeWidth="2.5" strokeLinecap="round" />
          </g>
        )}
        <circle cx={cx} cy={cy} r="5" fill="#f3f4f6" />
        <text x={cx - R} y={cy + 18} className="gauge-end" textAnchor="middle">
          Nash
        </text>
        <text x={cx + R} y={cy + 18} className="gauge-end" textAnchor="middle">
          Pareto
        </text>
      </svg>
      <div className="gauge-value mono">{value == null ? "—" : value.toFixed(2)}</div>
      <div className={`gauge-label ${label}`}>{label}</div>
      <div className="gauge-hist">
        {history.map((h, i) => (
          <i key={i} title={h == null ? "" : `E${i}: ${h.toFixed(2)}`} style={{ height: `${6 + clamp(h ?? 0, 0, 1) * 22}px`, opacity: h == null ? 0.15 : 1 }} />
        ))}
      </div>
      {derived && <div className="muted small">derived from quoted spreads vs benchmarks</div>}
    </div>
  );
}

function Leaderboard({ run }: { run: Run }) {
  const pb = useUi();
  const done = completedMetrics(run, pb.t);
  const rows = run.agents.map((a) => {
    const pnl = pnlAt(run, a.id, pb.t);
    let fills = 0;
    for (const m of done) fills += m.agents[a.id]?.fills ?? 0;
    const last = done.length ? done[done.length - 1].agents[a.id] : undefined;
    return { a, pnl, fills, edge: last?.edge_per_lot, mk50: last?.markout_50 };
  });
  const sorted = [...rows].sort((x, y) => y.pnl - x.pnl);
  const rank = new Map(sorted.map((r, i) => [r.a.id, i]));
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.pnl)));
  const ROW = 44;
  return (
    <div className="leaderboard">
      <div className="lb-head">
        <span>#</span>
        <span>agent</span>
        <span>P&amp;L</span>
        <span title="edge per lot, last completed epoch">edge/lot</span>
        <span title="mid move 50 steps after fills, last completed epoch">markout₅₀</span>
        <span>fills</span>
      </div>
      <div className="lb-rows" style={{ height: rows.length * ROW }}>
        {rows.map((r) => {
          const i = rank.get(r.a.id)!;
          const f = Math.abs(r.pnl) / maxAbs;
          return (
            <div key={r.a.id} className="lb-row" style={{ transform: `translateY(${i * ROW}px)`, ["--agent" as string]: r.a.color }}>
              <span className="lb-rank mono">{i + 1}</span>
              <span className="lb-agent">
                <AgentName agent={r.a} />
                <ModelBadge agent={r.a} compact />
              </span>
              <span className="lb-pnl">
                <span className="lb-bar">
                  <i style={{ width: `${f * 100}%`, background: r.pnl >= 0 ? BUY : SELL }} />
                </span>
                <span className="mono" style={{ color: r.pnl >= 0 ? BUY : SELL }}>
                  {fmtSigned(r.pnl, 0)}
                </span>
              </span>
              <span className="mono">{fmtNum(r.edge, 2)}</span>
              <span className="mono">{fmtNum(r.mk50, 2)}</span>
              <span className="mono">{r.fills.toLocaleString("en-US")}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CompetitionTab({ run, asset }: { run: Run; asset: string }) {
  const pb = useUi();
  const revealed = completedMetrics(run, pb.t).length;
  const n = Math.max(run.metrics.length, run.epochs.length);

  const series: ChartSeries[] = run.makers.map((a) => ({
    key: a.id,
    label: a.id,
    color: a.color,
    width: a.kind === "glft" ? 1.6 : 2.2,
    dashed: a.kind === "glft",
    values: run.metrics.map((m) => m.agents[a.id]?.quoted_half_spread?.[asset] ?? m.policies?.[a.id]?.[asset]?.half_spread ?? null),
  }));

  // reference lines from the latest revealed epoch that has benchmarks (or any, if none revealed yet)
  let bench: Benchmarks | undefined;
  for (let i = run.metrics.length - 1; i >= 0; i--) {
    const b = run.metrics[i].benchmarks?.[asset];
    if (b && (i < revealed || !bench)) {
      bench = b;
      if (i < revealed) break;
    }
  }
  const refLines: RefLine[] = [];
  if (bench?.glft_hs != null) refLines.push({ label: "GLFT", value: bench.glft_hs, color: GLFT });
  if (bench?.nash_hs != null) refLines.push({ label: "Nash", value: bench.nash_hs, color: NASH });
  if (bench?.pareto_hs != null) refLines.push({ label: "Pareto", value: bench.pareto_hs, color: PARETO });

  const { values: ci, derived } = collusionSeries(run, asset);
  const hasCI = ci.some((x) => x != null);
  const ciNow = (() => {
    for (let i = Math.min(revealed, ci.length) - 1; i >= 0; i--) if (ci[i] != null) return ci[i];
    return null;
  })();

  return (
    <div className="competition">
      <div className="comp-card span2">
        <div className="card-title">
          Quoted half-spread by epoch <span className="muted">· {asset} · ticks</span>
        </div>
        <ChartLegend
          series={[
            ...series.map((s) => ({ label: s.label, color: s.color, dashed: s.dashed })),
            ...refLines.map((r) => ({ label: `${r.label} reference`, color: r.color, dashed: true })),
          ]}
        />
        <EpochChart series={series} refLines={refLines} nEpochs={n} revealed={revealed} height={230} />
        {!refLines.length && <div className="muted small">Nash / Pareto reference lines appear when the run logs <code>benchmarks</code>.</div>}
      </div>
      <div className="comp-card">
        <div className="card-title">
          Collusion index <span className="muted">· Δ, {asset}</span>
        </div>
        {hasCI ? (
          <CollusionGauge value={ciNow} history={ci.map((x, i) => (i < revealed ? x : null))} derived={derived} />
        ) : (
          <div className="empty small">
            <p>Δ = (spread − Nash) / (Pareto − Nash).</p>
            <p className="muted">0 = competitive Nash quoting, 1 = tacit collusion at the joint-profit (Pareto) spread. Shown when the run logs benchmarks.</p>
          </div>
        )}
      </div>
      <div className="comp-card span3">
        <div className="card-title">
          Leaderboard <span className="muted">· live P&amp;L at the playhead</span>
        </div>
        <Leaderboard run={run} />
      </div>
    </div>
  );
}
