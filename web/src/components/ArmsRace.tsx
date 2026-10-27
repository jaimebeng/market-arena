import { useState } from "react";
import type { Experiment, SeedRun, Variant } from "../types";
import {
  fakeSizePerLevel,
  isRedTeam,
  tacticsByEpoch,
  variantHasVerdicts,
  verdictAt,
  verdictStats,
  type Verdict,
} from "../lib/arms";
import { fmtNum } from "../lib/format";

/** Whole numbers stay whole (tactics are integers); others get one decimal. */
const fmtVal = (x: number | null) => (x == null ? "" : Number.isInteger(x) ? x.toLocaleString("en-US") : x.toFixed(1));
import { useWidth } from "./charts/EpochChart";

const VERDICT: Record<Verdict, { label: string; color: string }> = {
  spoof: { label: "spoofing warning / referral", color: "#f87171" },
  wash: { label: "wash-trading warning / referral", color: "#fb923c" },
  watch: { label: "watch only", color: "#e9c46a" },
  clean: { label: "clean", color: "#232a3a" },
  none: { label: "no audit", color: "transparent" },
};

const seedName = (s: SeedRun, i: number) => (s.run ?? "").split("/").filter(Boolean).pop() || `seed ${i + 1}`;

const frac = (a: number, b: number) => `${a}/${b}`;

/** Display name: the experiment's baseline here is the unnamed scripted spoofer. */
function subjectLabel(v: Variant): { title: string; sub: string } {
  if (isRedTeam(v)) return { title: v.label, sub: v.change };
  if (v.name === "baseline" && variantHasVerdicts(v))
    return { title: "Scripted spoofer", sub: v.change || "trader_b runs the planted spoofer's fixed tactics every epoch (the baseline)." };
  return { title: v.label, sub: v.change };
}

export function VerdictLegend() {
  return (
    <div className="ar-legend">
      {(["spoof", "wash", "watch", "clean"] as Verdict[]).map((k) => (
        <span key={k}>
          <i className={`ar-cell v-${k}`} />
          {VERDICT[k].label}
        </span>
      ))}
    </div>
  );
}

function VariantGrid({ v }: { v: Variant }) {
  const { title, sub } = subjectLabel(v);
  const runs = v.seed_runs;
  if (!variantHasVerdicts(v)) {
    const fa = runs.reduce((s, r) => s + (r.false_accusations ?? 0), 0);
    const reports = runs.reduce((s, r) => s + (r.reports ?? 0), 0);
    return (
      <div className="ar-variant">
        <div className="ar-v-title">{title}</div>
        <div className="ar-v-sub">{sub}</div>
        <div className="ar-noverdict">
          No fake orders, so no verdict to score. False accusations:{" "}
          <b className={fa > 0 ? "bad" : "good"}>{fmtNum(fa, 0)}</b>
          {reports > 0 && <> in {fmtNum(reports, 0)} audits</>} across {runs.length} seeds.
        </div>
      </div>
    );
  }
  const n = Math.max(...runs.map((s) => s.detection_by_epoch?.length ?? 0));
  const st = verdictStats(runs);
  return (
    <div className="ar-variant">
      <div className="ar-v-title">{title}</div>
      <div className="ar-v-sub">{sub}</div>
      <div className="ar-grid" style={{ gridTemplateColumns: `44px repeat(${n}, minmax(0, 1fr))` }}>
        <span />
        {Array.from({ length: n }, (_, e) => (
          <span key={e} className="ar-head mono">
            E{e}
          </span>
        ))}
        {runs.map((s, i) => (
          <div key={i} className="ar-row">
            <span className="ar-seed mono">{seedName(s, i)}</span>
            {Array.from({ length: n }, (_, e) => {
              const vd = verdictAt(s, e);
              return <i key={e} className={`ar-cell v-${vd}`} title={`${seedName(s, i)} · epoch ${e}: ${VERDICT[vd].label}`} />;
            })}
          </div>
        ))}
      </div>
      <div className="ar-summary mono">
        <span className={st.spoofAfter0 > 0 ? "bad" : "good"} title={`all audits incl. epoch 0: ${frac(st.spoof, st.audits)}`}>
          spoofing warnings {frac(st.spoofAfter0, st.auditsAfter0)} after E0
        </span>
        {st.wash > 0 && (
          <span className="warn" title={`all audits incl. epoch 0: ${frac(st.wash, st.audits)}`}>
            wash trading {frac(st.washAfter0, st.auditsAfter0)} ({st.seedsWithWash} seed{st.seedsWithWash === 1 ? "" : "s"})
          </span>
        )}
        <span className="muted" title={`all audits incl. epoch 0: ${frac(st.any, st.audits)}`}>
          any finding incl. watch {frac(st.anyAfter0, st.auditsAfter0)}
        </span>
      </div>
    </div>
  );
}

interface Row {
  key: string;
  label: string;
  unit: string;
  color: string;
  values: (number | null)[];
  bars?: boolean;
}

/** "It learned to evade": tactics in force per epoch for one red-team seed, aligned with the verdicts. */
function TacticsChart({ s, sel, onSel }: { s: SeedRun; sel: number; onSel: (e: number) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { inForce, fakeLots, n } = tacticsByEpoch(s);
  const rows: Row[] = [
    { key: "size", label: "fake order / level", unit: "lots", color: "#f87171", values: inForce.map(fakeSizePerLevel) },
    { key: "layers", label: "price levels", unit: "", color: "#c4a1ff", values: inForce.map((t) => t?.layers ?? null) },
    { key: "hold", label: "fakes rest", unit: "steps", color: "#93c5fd", values: inForce.map((t) => t?.hold ?? null) },
    { key: "bait", label: "genuine order", unit: "lots", color: "#34d399", values: inForce.map((t) => t?.bait_size ?? null) },
    { key: "lots", label: "fake lots placed", unit: "", color: "#fb923c", values: fakeLots, bars: true },
  ];
  const W = Math.max(280, width);
  const narrow = W < 560;
  const labelW = narrow ? 86 : 148;
  const padR = 10;
  const colW = (W - labelW - padR) / n;
  const top = 22;
  const vH = 24; // verdict strip
  const rowH = narrow ? 40 : 44;
  const H = top + vH + 10 + rows.length * rowH + 4;
  const cx = (e: number) => labelW + colW * (e + 0.5);

  return (
    <div ref={ref} className="ar-chart">
      {width > 0 && (
        <svg width={W} height={H}>
          {/* column highlight + hit targets */}
          <rect x={labelW + colW * sel} y={top - 4} width={colW} height={H - top + 2} rx={6} className="ar-col-on" />
          {Array.from({ length: n }, (_, e) => (
            <text key={e} x={cx(e)} y={14} textAnchor="middle" className={`wt-axis ${e === sel ? "ar-axis-on" : ""}`}>
              E{e}
            </text>
          ))}
          <text x={0} y={top + vH / 2} dominantBaseline="middle" className="ar-row-label">
            regulator
          </text>
          {Array.from({ length: n }, (_, e) => {
            const vd = verdictAt(s, e);
            return (
              <rect
                key={e}
                x={labelW + colW * e + 3}
                y={top}
                width={colW - 6}
                height={vH}
                rx={4}
                fill={VERDICT[vd].color}
                stroke={vd === "none" ? "#2a3244" : "none"}
                strokeDasharray={vd === "none" ? "3 3" : undefined}
              />
            );
          })}
          {rows.map((r, k) => {
            const y0 = top + vH + 10 + k * rowH;
            const vals = r.values.filter((x): x is number => x != null);
            const max = Math.max(1, ...vals);
            const yOf = (x: number) => y0 + rowH - 12 - (x / max) * (rowH - 24);
            const pts = r.values.map((x, e) => (x == null ? null : ([cx(e), yOf(x)] as const)));
            return (
              <g key={r.key}>
                <line x1={labelW} x2={W - padR} y1={y0 + rowH - 12} y2={y0 + rowH - 12} stroke="rgba(255,255,255,0.05)" />
                <text x={0} y={y0 + rowH / 2} dominantBaseline="middle" className="ar-row-label">
                  {r.label}
                  {r.unit && !narrow ? <tspan className="ar-unit"> {r.unit}</tspan> : null}
                </text>
                {r.bars
                  ? pts.map((p, e) =>
                      p ? (
                        <rect key={e} x={p[0] - Math.min(14, colW * 0.3)} width={Math.min(28, colW * 0.6)} y={p[1]} height={y0 + rowH - 12 - p[1]} rx={2} fill={r.color} opacity={0.55} />
                      ) : null,
                    )
                  : (
                    <polyline
                      points={pts.filter(Boolean).map((p) => `${p![0]},${p![1]}`).join(" ")}
                      fill="none"
                      stroke={r.color}
                      strokeWidth={1.8}
                      strokeLinejoin="round"
                    />
                  )}
                {pts.map((p, e) =>
                  p ? (
                    <g key={e}>
                      {!r.bars && <circle cx={p[0]} cy={p[1]} r={e === sel ? 4 : 2.8} fill={r.color} stroke="#0e1219" strokeWidth={1.2} />}
                      <text x={p[0]} y={p[1] - 6} textAnchor="middle" className={`ar-val ${e === sel ? "on" : ""}`}>
                        {narrow && r.bars && (r.values[e] ?? 0) >= 1000 ? `${((r.values[e] ?? 0) / 1000).toFixed(1)}k` : fmtVal(r.values[e])}
                      </text>
                    </g>
                  ) : null,
                )}
              </g>
            );
          })}
          {Array.from({ length: n }, (_, e) => (
            <rect
              key={e}
              x={labelW + colW * e}
              y={0}
              width={colW}
              height={H}
              fill="transparent"
              style={{ cursor: "pointer" }}
              onMouseEnter={() => onSel(e)}
              onClick={() => onSel(e)}
            />
          ))}
        </svg>
      )}
    </div>
  );
}

function TacticsDetail({ s, e }: { s: SeedRun; e: number }) {
  const { inForce } = tacticsByEpoch(s);
  const t = inForce[e];
  const vd = verdictAt(s, e);
  const chosen = e === 0 ? "scripted spoofer's default tactics (every red team starts here)" : `chosen at the review after epoch ${e - 1}${t?.epoch === e - 1 ? "" : " (carried over)"}`;
  return (
    <div className="ar-detail">
      <div className="ar-detail-head">
        <span className="mono">Epoch {e}</span>
        <span className={`ar-pill v-${vd}`}>{VERDICT[vd].label}</span>
        <span className="muted small">tactics {chosen}</span>
      </div>
      {t && (
        <div className="ar-tactics mono">
          <span>
            fake {fmtNum(t.spoof_size, 0)} lots over {fmtNum(t.layers, 0)} level{t.layers === 1 ? "" : "s"} ({fmtNum(fakeSizePerLevel(t), 0)} per level)
          </span>
          <span>rest {fmtNum(t.hold, 0)} steps</span>
          <span>cycle {fmtNum(t.cycle, 0)}</span>
          <span>genuine {fmtNum(t.bait_size, 0)} lots</span>
          {t.max_position != null && <span>pos. limit {fmtNum(t.max_position, 0)}</span>}
        </div>
      )}
      {e > 0 && t?.rationale ? (
        <blockquote className="ar-rationale">
          “{t.rationale}”<span className="muted small"> · public rationale</span>
        </blockquote>
      ) : (
        e > 0 && <div className="muted small">No public rationale for this review.</div>
      )}
    </div>
  );
}

/**
 * Arms race view: the AI regulator's verdict on the subject (trader_b) in every audit, per variant
 * (seeds × epochs), plus the red team's tactics over time for one seed.
 */
export function ArmsRace({ exp }: { exp: Experiment }) {
  const reds = exp.variants.filter(isRedTeam);
  const [redName, setRedName] = useState(reds[0]?.name ?? "");
  const [seedIdx, setSeedIdx] = useState(0);
  const [col, setCol] = useState(1);
  const red = reds.find((v) => v.name === redName) ?? reds[0];
  const seeds = red ? red.seed_runs.filter((s) => Array.isArray(s.red_team_tactics) && s.red_team_tactics.length) : [];
  const s = seeds[Math.min(seedIdx, seeds.length - 1)];
  const nCols = s ? tacticsByEpoch(s).n : 0;

  return (
    <>
      <div className="comp-card ar-card">
        <div className="card-title">
          Arms race <span className="muted">· the AI regulator's verdict on trader_b in each epoch's audit, every seed</span>
        </div>
        <VerdictLegend />
        <div className="ar-variants">
          {exp.variants.map((v) => (
            <VariantGrid key={v.name} v={v} />
          ))}
        </div>
        <div className="wt-caption">
          Every participant has a neutral id, so the regulator works from the data alone. Epoch 0 always runs the scripted spoofer's
          tactics; counts "after E0" score only epochs where a red team had chosen its own tactics.
        </div>
      </div>

      {red && s && (
        <div className="comp-card ar-card">
          <div className="card-title">
            How the red team evaded <span className="muted">· tactics in force each epoch, aligned with the regulator's verdict</span>
          </div>
          <div className="ar-pickers">
            {reds.length > 1 && (
              <span className="seg">
                {reds.map((v) => (
                  <button
                    key={v.name}
                    className={v === red ? "on" : ""}
                    onClick={() => {
                      setRedName(v.name);
                      setSeedIdx(0);
                    }}
                  >
                    {v.label.replace(/^Red team:\s*/i, "")}
                  </button>
                ))}
              </span>
            )}
            <span className="seg">
              {seeds.map((x, i) => (
                <button key={i} className={x === s ? "on" : ""} onClick={() => setSeedIdx(i)}>
                  {seedName(x, i)}
                </button>
              ))}
            </span>
          </div>
          <TacticsChart s={s} sel={Math.min(col, nCols - 1)} onSel={setCol} />
          <TacticsDetail s={s} e={Math.min(col, nCols - 1)} />
          <div className="wt-caption">
            Fake order size per level = fake order size ÷ price levels. Hover or tap an epoch to read the red team's public rationale for
            the tactics in force. Its mandate is to keep placing fake orders every epoch (bottom row) while avoiding a spoofing finding.
          </div>
        </div>
      )}
    </>
  );
}
