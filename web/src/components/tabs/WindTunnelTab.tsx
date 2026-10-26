import { useEffect, useState } from "react";
import type { Experiment, ExperimentIndexEntry, Variant, VariantBenchmarks } from "../../types";
import { fetchExperiment, fetchExperiments } from "../../lib/load";
import { fmtCompact, fmtNum, fmtSigned, niceStep } from "../../lib/format";
import { CollusionGauge, DELTA_CAPTION } from "../CollusionGauge";
import { useWidth } from "../charts/EpochChart";

/** Rules the calibrated game benchmark does not model: Δ is not comparable for these. */
const UNMODELED = new Set(["speed_bump", "circuit_breaker"]);

const QUALITY: { key: keyof Variant & string; label: string; unit: string; better: "lower" | "higher" | null; digits: number }[] = [
  { key: "spread", label: "Spread", unit: "ticks", better: "lower", digits: 2 },
  { key: "depth", label: "Top-5 depth", unit: "lots", better: "higher", digits: 1 },
  { key: "mispricing_bps", label: "Mispricing |mid − V|", unit: "bps", better: "lower", digits: 1 },
  { key: "volatility", label: "Volatility", unit: "ticks/step", better: "lower", digits: 3 },
  { key: "llm_maker_half_spread", label: "LLM maker half-spread", unit: "ticks", better: null, digits: 2 },
  { key: "maker_pnl_per_epoch", label: "Maker P&L / epoch", unit: "", better: null, digits: 0 },
];

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const se = (v: Variant, k: string) => num(v[`${k}_se`]);
const firstBench = (v: Variant): VariantBenchmarks | undefined => (v.benchmarks ? Object.values(v.benchmarks)[0] : undefined);

const params = new URLSearchParams(window.location.search);

function QualityRow({ base, v, q }: { base: Variant; v: Variant; q: (typeof QUALITY)[number] }) {
  const b = num(base[q.key]);
  const x = num(v[q.key]);
  const bse = se(base, q.key) ?? 0;
  const xse = se(v, q.key) ?? 0;
  const max = Math.max(1e-9, (b ?? 0) + bse, (x ?? 0) + xse) * 1.08;
  const pct = b != null && x != null && b !== 0 ? ((x - b) / Math.abs(b)) * 100 : null;
  const noise = 2 * Math.sqrt(bse * bse + xse * xse);
  const sig = b != null && x != null && (bse > 0 || xse > 0) ? Math.abs(x - b) > noise : null;
  const good = pct == null || q.better == null ? null : q.better === "lower" ? pct < 0 : pct > 0;
  const bar = (val: number | null, s: number, cls: string) => (
    <div className="wt-bar-row">
      <div className="wt-track">
        {val != null && <i className={`wt-bar ${cls}`} style={{ width: `${(Math.max(0, val) / max) * 100}%` }} />}
        {val != null && s > 0 && (
          <i className="wt-whisker" style={{ left: `${(Math.max(0, val - s) / max) * 100}%`, width: `${((Math.min(max, val + s) - Math.max(0, val - s)) / max) * 100}%` }} />
        )}
      </div>
      <span className="mono wt-num">
        {fmtNum(val, q.digits)}
        {s > 0 && <span className="muted"> ±{fmtNum(s, q.digits)}</span>}
      </span>
    </div>
  );
  return (
    <div className="wt-q">
      <div className="wt-q-head">
        <span>{q.label}</span>
        {q.unit && <span className="muted small">{q.unit}</span>}
        <span className="spacer" />
        {pct != null && (
          <span className={`wt-pct ${good == null ? "" : good ? "good" : "bad"}`} title={sig == null ? "" : sig ? "difference > 2 standard errors" : "within 2 standard errors (noise)"}>
            {fmtSigned(pct, 1)}%{sig === false && <span className="muted"> · noise</span>}
          </span>
        )}
      </div>
      {bar(b, bse, "base")}
      {bar(x, xse, "variant")}
    </div>
  );
}

/** Small multiple: LLM makers' quoted half-spread per epoch, one thin line per seed, with Nash→Pareto band. */
function SpreadMultiple({ v, domain, title, accent }: { v: Variant; domain: [number, number]; title: string; accent: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const H = 170;
  const padL = 34;
  const padR = 52;
  const padT = 8;
  const padB = 20;
  const W = Math.max(120, width);
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const n = Math.max(2, ...v.seed_runs.map((s) => s.llm_half_spread_by_epoch?.length ?? 0));
  const [lo, hi] = domain;
  const xOf = (e: number) => padL + (e / (n - 1)) * plotW;
  const yOf = (y: number) => padT + ((hi - y) / (hi - lo)) * plotH;
  const bm = firstBench(v);
  const step = niceStep(hi - lo, 4);
  const ticks: number[] = [];
  for (let y = Math.ceil(lo / step) * step; y <= hi; y += step) ticks.push(y);
  return (
    <div className="wt-multiple">
      <div className="wt-mult-title">
        <i style={{ background: accent }} /> {title} <span className="muted">· {v.seed_runs.length} seed{v.seed_runs.length > 1 ? "s" : ""}</span>
      </div>
      <div ref={ref}>
        {width > 0 && (
          <svg width={W} height={H}>
            {ticks.map((y) => (
              <g key={y}>
                <line x1={padL} x2={padL + plotW} y1={yOf(y)} y2={yOf(y)} stroke="rgba(255,255,255,0.05)" />
                <text x={padL - 6} y={yOf(y)} className="wt-axis" textAnchor="end" dominantBaseline="middle">
                  {fmtCompact(y)}
                </text>
              </g>
            ))}
            {bm?.nash_hs != null && bm?.pareto_hs != null && (
              <>
                <rect x={padL} width={plotW} y={yOf(bm.pareto_hs)} height={Math.max(1, yOf(bm.nash_hs) - yOf(bm.pareto_hs))} className="wt-band" />
                <line x1={padL} x2={padL + plotW} y1={yOf(bm.nash_hs)} y2={yOf(bm.nash_hs)} stroke="#cbd5e1" strokeDasharray="5 4" />
                <line x1={padL} x2={padL + plotW} y1={yOf(bm.pareto_hs)} y2={yOf(bm.pareto_hs)} stroke="#f87171" strokeDasharray="5 4" />
                <text x={padL + plotW + 5} y={yOf(bm.nash_hs)} className="wt-ref" fill="#cbd5e1" dominantBaseline="middle">
                  Nash
                </text>
                <text x={padL + plotW + 5} y={yOf(bm.pareto_hs)} className="wt-ref" fill="#f87171" dominantBaseline="middle">
                  Pareto
                </text>
              </>
            )}
            {bm?.glft_hs != null && (
              <line x1={padL} x2={padL + plotW} y1={yOf(bm.glft_hs)} y2={yOf(bm.glft_hs)} stroke="#f5b841" strokeDasharray="2 3" opacity={0.8}>
                <title>GLFT optimal {bm.glft_hs.toFixed(2)}</title>
              </line>
            )}
            {Array.from({ length: n }, (_, e) => (
              <text key={e} x={xOf(e)} y={H - 5} className="wt-axis" textAnchor="middle">
                E{e}
              </text>
            ))}
            {v.seed_runs.map((s, k) => {
              const pts = (s.llm_half_spread_by_epoch ?? [])
                .map((y, e) => (y == null ? null : `${xOf(e)},${yOf(y)}`))
                .filter(Boolean)
                .join(" ");
              return (
                <polyline key={k} points={pts} fill="none" stroke={accent} strokeWidth={1.3} opacity={0.75} strokeLinejoin="round">
                  <title>{s.run ?? `seed ${k}`}</title>
                </polyline>
              );
            })}
          </svg>
        )}
      </div>
    </div>
  );
}

function LeverCard({ v, base, on, onClick }: { v: Variant; base?: Variant; on: boolean; onClick: () => void }) {
  const d0 = num(base?.collusion_index);
  const d1 = num(v.collusion_index);
  const s0 = num(base?.spread);
  const s1 = num(v.spread);
  const sp = s0 && s1 != null ? ((s1 - s0) / s0) * 100 : null;
  return (
    <button className={`lever ${on ? "on" : ""}`} onClick={onClick}>
      <div className="lever-head">
        <span className="lever-label">{v.label}</span>
        {v.provisional && <span className="prov-dot" title="summarised from runs (provisional)" />}
      </div>
      <div className="lever-change">{v.change}</div>
      <div className="lever-stats mono">
        <span title="collusion index Δ, baseline → variant">
          Δ {fmtNum(d0, 2)} → <b>{fmtNum(d1, 2)}</b>
        </span>
        {sp != null && <span className={sp < 0 ? "good" : "bad"}>spread {fmtSigned(sp, 0)}%</span>}
      </div>
    </button>
  );
}

export function WindTunnelTab() {
  const [index, setIndex] = useState<ExperimentIndexEntry[] | null>(null);
  const [exp, setExp] = useState<Experiment | null>(null);
  const [sel, setSel] = useState<string | null>(params.get("lever"));
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchExperiments()
      .then((idx) => {
        setIndex(idx);
        const want = params.get("exp");
        const e = idx.find((x) => x.name === want) ?? idx[0];
        if (e) return fetchExperiment(e).then(setExp);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="error-banner">{err}</div>;
  if (!index) return <div className="muted">loading experiments…</div>;
  if (!index.length || !exp)
    return (
      <div className="empty">
        <div className="empty-title">No wind-tunnel experiments exported</div>
        <p>
          Run <code>python scripts/export_experiment.py --all runs web/public/experiments</code> after a wind-tunnel experiment.
        </p>
      </div>
    );

  const base = exp.variants.find((v) => v.name === "baseline");
  const levers = exp.variants.filter((v) => v.name !== "baseline");
  const v = levers.find((x) => x.name === sel) ?? levers[0] ?? base!;
  const ref = base ?? v;

  // shared y-domain for the small multiples
  const ys: number[] = [];
  for (const x of [ref, v]) {
    for (const s of x.seed_runs) for (const y of s.llm_half_spread_by_epoch ?? []) if (y != null) ys.push(y);
    const b = firstBench(x);
    for (const y of [b?.nash_hs, b?.pareto_hs, b?.glft_hs]) if (y != null) ys.push(y);
  }
  const lo = ys.length ? Math.min(...ys) : 0;
  const hi = ys.length ? Math.max(...ys) : 1;
  const pad = (hi - lo) * 0.1 || 1;
  const domain: [number, number] = [Math.max(0, lo - pad), hi + pad];
  const dd = num(v.collusion_index) != null && num(ref.collusion_index) != null ? v.collusion_index! - ref.collusion_index! : null;

  return (
    <div className="wt">
      <div className="tab-toolbar">
        <select
          className="wt-select"
          value={exp.experiment}
          onChange={(e) => {
            const entry = index.find((x) => x.name === e.target.value);
            if (entry) fetchExperiment(entry).then(setExp);
          }}
        >
          {index.map((x) => (
            <option key={x.name} value={x.name}>
              {x.name} · {x.variants.length} variants{x.seeds.length ? ` · ${x.seeds.length} seeds` : ""}
            </option>
          ))}
        </select>
        <span className="muted">{exp.description}</span>
        <span className="spacer" />
        {exp.seeds.length > 0 && <span className="chip mono">seeds {exp.seeds.join(", ")}</span>}
        {exp.provisional && (
          <span className="chip prov" title="Some variants have no summary.json entry yet; summarised here from their run folders">
            provisional · from runs in progress
          </span>
        )}
      </div>

      <div className="levers">
        {levers.map((x) => (
          <LeverCard key={x.name} v={x} base={base} on={x === v} onClick={() => setSel(x.name)} />
        ))}
      </div>

      <div className="wt-compare">
        <div className="comp-card">
          <div className="card-title">
            Market quality <span className="muted">· baseline vs {v.label}, mean ± s.e. over seeds</span>
          </div>
          <div className="wt-legend">
            <span>
              <i className="wt-sw base" /> baseline
            </span>
            <span>
              <i className="wt-sw variant" /> {v.label}
            </span>
          </div>
          {QUALITY.map((q) => (
            <QualityRow key={q.key} base={ref} v={v} q={q} />
          ))}
        </div>

        <div className="comp-card">
          <div className="card-title">
            Collusion index Δ <span className="muted">· LLM makers</span>
          </div>
          <div className="wt-gauges">
            <CollusionGauge title="baseline" value={num(ref.collusion_index)} size={230} note={se(ref, "collusion_index") != null ? `± ${fmtNum(se(ref, "collusion_index"), 2)} s.e.` : undefined} />
            <CollusionGauge title={v.label} value={num(v.collusion_index)} size={230} note={se(v, "collusion_index") != null ? `± ${fmtNum(se(v, "collusion_index"), 2)} s.e.` : undefined} />
          </div>
          {dd != null && (
            <div className="wt-dd">
              change in Δ <b className="mono">{fmtSigned(dd, 2)}</b> {dd > 0 ? "toward cooperation" : "toward competition"}
            </div>
          )}
          {UNMODELED.has(v.name) && <div className="wt-warn">Benchmark doesn't model this rule — compare spreads, not Δ.</div>}
          <div className="wt-caption">{DELTA_CAPTION}</div>
        </div>

        <div className="comp-card">
          <div className="card-title">
            Quoted half-spread per epoch <span className="muted">· LLM makers, one line per seed</span>
          </div>
          <SpreadMultiple v={ref} domain={domain} title="baseline" accent="#8b93a7" />
          <SpreadMultiple v={v} domain={domain} title={v.label} accent="#7b8cff" />
          <div className="muted small">
            Band: Nash (dashed white) to Pareto (dashed red) half-spread for this rule set; dotted amber: GLFT optimum.
          </div>
        </div>
      </div>
    </div>
  );
}
