import { useEffect, useState } from "react";
import type { Experiment, ExperimentIndexEntry, SeedRun, Variant, VariantBenchmarks, VariantScalars } from "../../types";
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

function setUrlParam(k: string, v: string) {
  const p = new URLSearchParams(window.location.search);
  p.set(k, v);
  window.history.replaceState(null, "", `${window.location.pathname}?${p}`);
}

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

/** Fixed colour order for non-baseline variants (colour follows the variant, never its rank). */
const VARIANT_COLORS = ["#7b8cff", "#f472b6", "#fde047", "#2dd4bf", "#fb923c", "#c4a1ff"];
const BASE_COLOR = "#5b6478";

const seedOf = (run?: string) => (run ?? "").split("/").filter(Boolean).pop() ?? "";

/** Per-seed paired differences variant − baseline for one metric (for the seed dots). */
function pairedSeeds(v: Variant, base: Variant | undefined, key: keyof SeedRun): { seed: string; d: number }[] {
  if (!base) return [];
  const by = new Map(base.seed_runs.map((s) => [seedOf(s.run), num(s[key])]));
  return v.seed_runs
    .map((s) => {
      const b = by.get(seedOf(s.run));
      const x = num(s[key]);
      return b != null && x != null ? { seed: seedOf(s.run), d: x - b } : null;
    })
    .filter((x): x is { seed: string; d: number } => x != null);
}

type DeltaMode = "paired" | "raw";

/**
 * Collusion index Δ per variant with standard-error bars and per-seed dots.
 * paired: variant − baseline on the same seed (zero line = baseline); raw: mean Δ per variant
 * against the Nash (0) and Pareto (1) references.
 */
function DeltaByVariant({ exp, mode, sel, onPick }: { exp: Experiment; mode: DeltaMode; sel?: string; onPick: (name: string) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const base = exp.variants.find((v) => v.name === "baseline");
  const others = exp.variants.filter((v) => v.name !== "baseline");
  const colorOf = (v: Variant) => (v.name === "baseline" ? BASE_COLOR : VARIANT_COLORS[others.indexOf(v) % VARIANT_COLORS.length]);
  const items = (mode === "paired" ? others : exp.variants).map((v) => {
    if (mode === "paired") {
      const p = v.vs_baseline?.collusion_index;
      return { v, mean: num(p?.mean), se: num(p?.se), n: p?.n ?? 0, dots: pairedSeeds(v, base, "collusion_index").map((x) => ({ seed: x.seed, y: x.d })) };
    }
    return {
      v,
      mean: num(v.collusion_index),
      se: se(v, "collusion_index"),
      n: v.n_seeds,
      dots: v.seed_runs.map((s) => ({ seed: seedOf(s.run), y: num(s.collusion_index) })).filter((d): d is { seed: string; y: number } => d.y != null),
    };
  });
  const ys = [0, ...(mode === "raw" ? [1] : [])];
  for (const it of items) {
    if (it.mean != null) ys.push(it.mean - (it.se ?? 0), it.mean + (it.se ?? 0));
    for (const d of it.dots) ys.push(d.y);
  }
  let lo = Math.min(...ys);
  let hi = Math.max(...ys);
  const pad = (hi - lo) * 0.12 || 0.5;
  lo -= pad;
  hi += pad;
  const H = 270;
  const padL = mode === "paired" ? 60 : 44;
  const padR = mode === "raw" ? 52 : 16;
  const padT = 14;
  const padB = 44;
  const W = Math.max(260, width);
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const yOf = (y: number) => padT + ((hi - y) / (hi - lo)) * plotH;
  const slot = plotW / Math.max(1, items.length);
  const barW = Math.min(64, slot * 0.46);
  const step = niceStep(hi - lo, 5);
  const ticks: number[] = [];
  for (let y = Math.ceil(lo / step) * step; y <= hi + 1e-9; y += step) ticks.push(Math.round(y / step) * step);

  return (
    <div ref={ref} className="dv">
      {width > 0 && (
        <svg width={W} height={H}>
          {ticks.map((y) => (
            <g key={y}>
              <line x1={padL} x2={padL + plotW} y1={yOf(y)} y2={yOf(y)} stroke="rgba(255,255,255,0.05)" />
              <text x={padL - 6} y={yOf(y)} className="wt-axis" textAnchor="end" dominantBaseline="middle">
                {mode === "paired" && y === 0 ? "baseline" : `${mode === "paired" && y > 0 ? "+" : ""}${fmtNum(y, step < 0.1 ? 2 : 1)}`}
              </text>
            </g>
          ))}
          {mode === "paired" ? (
            <>
              <line x1={padL} x2={padL + plotW} y1={yOf(0)} y2={yOf(0)} stroke="#cbd5e1" strokeWidth={1.2} />
            </>
          ) : (
            <>
              <line x1={padL} x2={padL + plotW} y1={yOf(0)} y2={yOf(0)} stroke="#cbd5e1" strokeDasharray="5 4" />
              <line x1={padL} x2={padL + plotW} y1={yOf(1)} y2={yOf(1)} stroke="#f87171" strokeDasharray="5 4" />
              <text x={padL + plotW + 5} y={yOf(0)} className="wt-ref" fill="#cbd5e1" dominantBaseline="middle">
                Nash
              </text>
              <text x={padL + plotW + 5} y={yOf(1)} className="wt-ref" fill="#f87171" dominantBaseline="middle">
                Pareto
              </text>
            </>
          )}
          {items.map((it, i) => {
            const cx = padL + slot * (i + 0.5);
            const c = colorOf(it.v);
            const m = it.mean;
            const y0 = yOf(0);
            const y1 = m != null ? yOf(m) : y0;
            const top = Math.min(y0, y1);
            const h = Math.max(1, Math.abs(y1 - y0));
            const s = it.se ?? 0;
            const on = it.v.name === sel;
            const tip =
              `${it.v.label}: ${mode === "paired" ? "Δ change vs baseline" : "Δ"} ${m != null ? fmtSigned(m, 2) : "—"}` +
              (it.se != null ? ` ± ${fmtNum(it.se, 2)} s.e.` : "") +
              ` (n=${it.n})` +
              (it.dots.length ? `\nper seed: ${it.dots.map((d) => `${d.seed} ${fmtSigned(d.y, 2)}`).join(", ")}` : "");
            return (
              <g key={it.v.name} className={`dv-item ${on ? "on" : ""}`} onClick={() => it.v.name !== "baseline" && onPick(it.v.name)}>
                <title>{tip}</title>
                <rect x={cx - slot / 2} y={padT} width={slot} height={plotH} fill="transparent" />
                {m != null && <rect x={cx - barW / 2} y={top} width={barW} height={h} rx={3} fill={c} opacity={on ? 0.95 : 0.7} />}
                {m != null && s > 0 && (
                  <g stroke="#e7eaf1" strokeWidth={1.4}>
                    <line x1={cx} x2={cx} y1={yOf(m - s)} y2={yOf(m + s)} />
                    <line x1={cx - 7} x2={cx + 7} y1={yOf(m - s)} y2={yOf(m - s)} />
                    <line x1={cx - 7} x2={cx + 7} y1={yOf(m + s)} y2={yOf(m + s)} />
                  </g>
                )}
                {it.dots.map((d, k) => (
                  <circle key={k} cx={cx + barW / 2 + 9 + (k % 3) * 6} cy={yOf(d.y)} r={3} fill={c} stroke="#0e1219" strokeWidth={1.5} />
                ))}
                {m != null && (
                  <text x={cx} y={m >= 0 ? yOf(m + s) - 6 : yOf(m - s) + 13} textAnchor="middle" className="dv-val">
                    {mode === "paired" ? fmtSigned(m, 2) : fmtNum(m, 2)}
                  </text>
                )}
                <text x={cx} y={H - padB + 18} textAnchor="middle" className={`dv-label ${on ? "on" : ""}`}>
                  {it.v.label}
                </text>
                <text x={cx} y={H - padB + 32} textAnchor="middle" className="wt-axis">
                  n={it.n}
                  {it.v.provisional ? " · prov." : ""}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

const pct = (x: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

/** Chat activity and the AI regulator's record per variant (collusion lab). */
function ConductTable({ exp }: { exp: Experiment }) {
  const cols: { key: keyof VariantScalars & string; label: string; title: string; fmt: (x: number | null) => string; tone?: (x: number) => string }[] = [
    { key: "chat_messages", label: "chat msgs", title: "maker chat messages per run", fmt: (x) => fmtNum(x, 1) },
    { key: "regulator_notices", label: "notices", title: "public notices posted by the regulator per run", fmt: (x) => fmtNum(x, 1) },
    { key: "reports", label: "reports", title: "surveillance reports filed per run", fmt: (x) => fmtNum(x, 1) },
    { key: "spoofer_detection_rate", label: "spoofer caught", title: "share of reports that flag the planted spoofer for spoofing (warning or referral)", fmt: pct, tone: (x) => (x >= 0.5 ? "good" : "bad") },
    { key: "first_detection_epoch", label: "first caught", title: "epoch of the first report that flags the spoofer", fmt: (x) => (x == null ? "—" : `E${fmtNum(x, x % 1 ? 1 : 0)}`) },
    { key: "false_accusations", label: "false accus.", title: "spoofing / wash-trading findings (warning+) against innocent agents, per run", fmt: (x) => fmtNum(x, 1), tone: (x) => (x > 0 ? "bad" : "good") },
    { key: "collusion_flags", label: "collusion flags", title: "explicit / tacit collusion findings (warning+) per run", fmt: (x) => fmtNum(x, 1) },
  ];
  const used = cols.filter((c) => exp.variants.some((v) => num(v[c.key]) != null));
  return (
    <table className="conduct-table">
      <thead>
        <tr>
          <th>variant</th>
          {used.map((c) => (
            <th key={c.key} title={c.title}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {exp.variants.map((v) => (
          <tr key={v.name}>
            <td>{v.label}</td>
            {used.map((c) => {
              const x = num(v[c.key]);
              const s = se(v, c.key);
              const seeds = v.seed_runs.map((r) => `${seedOf(r.run)}: ${c.fmt(num(r[c.key]))}`).join(", ");
              return (
                <td key={c.key} className={`mono ${x != null && c.tone ? c.tone(x) : ""}`} title={seeds}>
                  {c.fmt(x)}
                  {s != null && s > 0 && c.key !== "spoofer_detection_rate" && <span className="muted"> ±{fmtNum(s, 1)}</span>}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LeverCard({ v, base, on, onClick }: { v: Variant; base?: Variant; on: boolean; onClick: () => void }) {
  const d0 = num(base?.collusion_index);
  const d1 = num(v.collusion_index);
  const s0 = num(base?.spread);
  const s1 = num(v.spread);
  const sp = s0 && s1 != null ? ((s1 - s0) / s0) * 100 : null;
  const paired = v.vs_baseline?.collusion_index;
  return (
    <button className={`lever ${on ? "on" : ""}`} onClick={onClick}>
      <div className="lever-head">
        <span className="lever-label">{v.label}</span>
        {v.provisional && <span className="prov-dot" title="summarised from runs (provisional)" />}
      </div>
      <div className="lever-change">{v.change}</div>
      <div className="lever-stats mono">
        {paired?.mean != null ? (
          <span title="paired change in collusion index Δ vs baseline on the same seed, ± s.e.">
            ΔΔ <b>{fmtSigned(paired.mean, 2)}</b>
            {paired.se != null && <> ±{fmtNum(paired.se, 2)}</>}
          </span>
        ) : (
          <span title="collusion index Δ, baseline → variant">
            Δ {fmtNum(d0, 2)} → <b>{fmtNum(d1, 2)}</b>
          </span>
        )}
        {sp != null && <span className={sp < 0 ? "good" : "bad"}>spread {fmtSigned(sp, 0)}%</span>}
      </div>
      {(num(v.chat_messages) != null || num(v.spoofer_detection_rate) != null) && (
        <div className="lever-stats mono lever-conduct">
          {num(v.chat_messages) != null && <span>chat {fmtNum(v.chat_messages, 1)}/run</span>}
          {num(v.spoofer_detection_rate) != null && (
            <span className={v.spoofer_detection_rate! >= 0.5 ? "good" : "bad"}>spoofer caught {pct(num(v.spoofer_detection_rate))}</span>
          )}
          {num(v.false_accusations) != null && <span className={v.false_accusations! > 0 ? "bad" : ""}>false acc. {fmtNum(v.false_accusations, 1)}</span>}
        </div>
      )}
    </button>
  );
}

export function WindTunnelTab() {
  const [index, setIndex] = useState<ExperimentIndexEntry[] | null>(null);
  const [exp, setExp] = useState<Experiment | null>(null);
  const [sel, setSel] = useState<string | null>(params.get("lever"));
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<DeltaMode | null>((params.get("delta") as DeltaMode) || null);

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
  const isLab = exp.variants.some((x) => num(x.chat_messages) != null || num(x.reports) != null);
  const hasPaired = levers.some((x) => x.vs_baseline?.collusion_index?.mean != null);
  const dMode: DeltaMode = mode ?? (hasPaired ? "paired" : "raw");
  const pickLever = (name: string) => {
    setSel(name);
    setUrlParam("lever", name);
  };
  const deltaCard = (
    <div className="comp-card dv-card">
      <div className="card-title">
        Collusion index Δ by variant{" "}
        <span className="muted">
          {dMode === "paired"
            ? "· change vs baseline on the same seed, mean ± s.e.; dots = seeds"
            : "· LLM makers, mean ± s.e. over seeds; dots = seeds"}
        </span>
        <span className="spacer" />
        <span className="seg">
          <button className={dMode === "paired" ? "on" : ""} disabled={!hasPaired} onClick={() => setMode("paired")} title="variant − baseline, paired by seed">
            paired vs baseline
          </button>
          <button className={dMode === "raw" ? "on" : ""} onClick={() => setMode("raw")} title="raw Δ per variant">
            raw Δ
          </button>
        </span>
      </div>
      <DeltaByVariant exp={exp} mode={dMode} sel={v.name} onPick={pickLever} />
      <div className="wt-caption">
        {dMode === "paired"
          ? "Bars above zero: the variant pushed makers toward the joint-profit (Pareto) spread relative to the same seed's baseline; below zero: toward competition. "
          : "0 = competitive Nash quoting, 1 = tacit collusion at the joint-profit (Pareto) spread. "}
        {exp.variants.some((x) => UNMODELED.has(x.name)) && "Speed bump / circuit breaker are not modelled by the benchmark: compare spreads, not Δ. "}
        Click a bar to compare that variant below.
      </div>
    </div>
  );

  return (
    <div className="wt">
      <div className="tab-toolbar">
        <select
          className="wt-select"
          value={exp.experiment}
          onChange={(e) => {
            const entry = index.find((x) => x.name === e.target.value);
            if (entry) {
              setUrlParam("exp", entry.name);
              fetchExperiment(entry).then(setExp);
            }
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

      {isLab && (
        <div className="lab-top">
          {deltaCard}
          <div className="comp-card">
            <div className="card-title">
              Conduct <span className="muted">· chat activity and the AI regulator's record, mean per run (hover for seeds)</span>
            </div>
            <ConductTable exp={exp} />
            <div className="wt-caption">
              Detection is scored against the planted ground truth: a scripted spoofer trades in every variant; only the regulator variant has anyone looking for it.
              False accusations count spoofing / wash-trading findings (warning or referral) against agents that are not the spoofer.
            </div>
          </div>
        </div>
      )}

      <div className="levers">
        {levers.map((x) => (
          <LeverCard key={x.name} v={x} base={base} on={x === v} onClick={() => pickLever(x.name)} />
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
      {!isLab && <div className="wt-bottom">{deltaCard}</div>}
    </div>
  );
}
