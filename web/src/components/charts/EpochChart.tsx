import { useEffect, useRef, useState, type RefObject } from "react";
import { niceStep } from "../../lib/format";

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  values: (number | null | undefined)[];
  dashed?: boolean;
  width?: number;
}

export interface RefLine {
  label: string;
  value: number;
  color: string;
  dash?: string;
}

export function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/**
 * SVG line chart over epochs. Points after `revealed` (number of completed epochs) are hidden
 * so the chart builds up as the replay plays.
 */
export function EpochChart({
  series,
  refLines = [],
  nEpochs,
  revealed,
  height = 200,
  format = (v) => v.toFixed(2),
  zeroLine = false,
}: {
  series: ChartSeries[];
  refLines?: RefLine[];
  nEpochs: number;
  revealed: number;
  height?: number;
  format?: (v: number) => string;
  zeroLine?: boolean;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const padL = 44;
  const padR = refLines.length ? 92 : 16;
  const padT = 12;
  const padB = 24;
  const W = Math.max(100, width);
  const plotW = W - padL - padR;
  const plotH = height - padT - padB;

  const vals: number[] = [];
  for (const s of series) for (const v of s.values) if (v != null && Number.isFinite(v)) vals.push(v);
  for (const r of refLines) vals.push(r.value);
  if (zeroLine) vals.push(0);
  let lo = vals.length ? Math.min(...vals) : 0;
  let hi = vals.length ? Math.max(...vals) : 1;
  if (hi - lo < 1e-9) {
    hi += 1;
    lo -= 1;
  }
  const span = hi - lo;
  lo -= span * 0.08;
  hi += span * 0.08;
  const step = niceStep(hi - lo, 4);
  const n = Math.max(1, nEpochs);
  const xOf = (e: number) => padL + (n === 1 ? plotW / 2 : (e / (n - 1)) * plotW);
  const yOf = (v: number) => padT + ((hi - v) / (hi - lo)) * plotH;
  const revX = revealed >= n ? padL + plotW : xOf(Math.max(0, revealed - 0.5));

  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);

  return (
    <div ref={ref} className="epoch-chart">
      {width > 0 && (
        <svg width={W} height={height}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={padL} x2={padL + plotW} y1={yOf(v)} y2={yOf(v)} className="grid" />
              <text x={padL - 8} y={yOf(v)} className="axis" textAnchor="end" dominantBaseline="middle">
                {format(v)}
              </text>
            </g>
          ))}
          {zeroLine && <line x1={padL} x2={padL + plotW} y1={yOf(0)} y2={yOf(0)} className="zero" />}
          {Array.from({ length: n }, (_, e) => (
            <text key={e} x={xOf(e)} y={height - 6} className={`axis ${e < revealed ? "" : "dim"}`} textAnchor="middle">
              E{e}
            </text>
          ))}
          {revealed < n && <rect x={revX} y={padT} width={padL + plotW - revX} height={plotH} className="future" />}
          {refLines.map((r) => (
            <g key={r.label}>
              <line x1={padL} x2={padL + plotW} y1={yOf(r.value)} y2={yOf(r.value)} stroke={r.color} strokeDasharray={r.dash ?? "5 4"} strokeWidth={1.3} opacity={0.85} />
              <text x={padL + plotW + 6} y={yOf(r.value)} fill={r.color} className="ref-label" dominantBaseline="middle">
                {r.label} {format(r.value)}
              </text>
            </g>
          ))}
          {series.map((s) => {
            const pts = s.values
              .map((v, e) => (v != null && Number.isFinite(v) && e < revealed ? [xOf(e), yOf(v), v] : null))
              .filter((p): p is number[] => p !== null);
            if (!pts.length) return null;
            const last = pts[pts.length - 1];
            return (
              <g key={s.key}>
                <polyline
                  points={pts.map((p) => `${p[0]},${p[1]}`).join(" ")}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={s.width ?? 2}
                  strokeDasharray={s.dashed ? "4 3" : undefined}
                  strokeLinejoin="round"
                />
                {pts.map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r={i === pts.length - 1 ? 4 : 2.6} fill={i === pts.length - 1 ? s.color : "#0c0f15"} stroke={s.color} strokeWidth={1.5}>
                    <title>
                      {s.label}: {format(p[2])}
                    </title>
                  </circle>
                ))}
                <circle cx={last[0]} cy={last[1]} r={9} fill={s.color} opacity={0.15} />
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

export function ChartLegend({ series }: { series: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="chart-legend">
      {series.map((s) => (
        <span key={s.label} className="legend-item">
          <i className={s.dashed ? "swatch-dash" : "swatch-line"} style={s.dashed ? { borderColor: s.color } : { background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}
