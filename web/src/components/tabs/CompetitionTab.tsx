import type { Benchmarks, Run } from "../../types";
import { BUY, SELL } from "../../lib/agents";
import { fmtNum, fmtSigned } from "../../lib/format";
import { useUi } from "../../lib/playback";
import { completedMetrics, pnlAt } from "../../lib/query";
import { ChartLegend, EpochChart, type ChartSeries, type RefLine } from "../charts/EpochChart";
import { AgentName, ModelBadge } from "../ModelBadge";
import { CollusionGauge, DELTA_CAPTION } from "../CollusionGauge";
import { ChatRoom } from "../Surveillance";

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

function Leaderboard({ run }: { run: Run }) {
  // P&L moves continuously: refresh on a coarse grid of the replay clock (≤ 400 updates per run)
  const pb = useUi((p) => Math.round(p.t / Math.max(1, run.tEnd / 400)));
  const done = completedMetrics(run, pb.t);
  const rows = run.traders.map((a) => {
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
  const pb = useUi((p) => completedMetrics(run, p.t).length);
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

  const hasChat = run.chat.length > 0 || !!(run.config.chat as { enabled?: boolean } | undefined)?.enabled;
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
          <CollusionGauge
            value={ciNow}
            history={ci.map((x, i) => (i < revealed ? x : null))}
            note={derived ? "derived from quoted spreads vs benchmarks. " + DELTA_CAPTION : DELTA_CAPTION}
          />
        ) : (
          <div className="empty small">
            <p>Δ = (spread − Nash) / (Pareto − Nash).</p>
            <p className="muted">0 = competitive Nash quoting, 1 = tacit collusion at the joint-profit (Pareto) spread. Shown when the run logs benchmarks.</p>
          </div>
        )}
      </div>
      <div className={`comp-card ${hasChat ? "span2" : "span3"}`}>
        <div className="card-title">
          Leaderboard{" "}
          <span className="muted">
            · live P&amp;L at the playhead{run.regulators.length ? " · the regulator does not trade and is not ranked" : ""}
          </span>
        </div>
        <Leaderboard run={run} />
      </div>
      {hasChat && (
        <div className="comp-card">
          <ChatRoom run={run} maxHeight={Math.max(200, run.traders.length * 44 + 20)} />
        </div>
      )}
    </div>
  );
}
