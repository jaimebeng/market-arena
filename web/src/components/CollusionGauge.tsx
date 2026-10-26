import { useId } from "react";
import { clamp } from "../lib/format";

export const DELTA_CAPTION =
  "Δ = (s − s_Nash)/(s_Pareto − s_Nash), benchmarks calibrated to the simulator incl. adverse selection; stylised model, a yardstick not a theorem.";

export function deltaLabel(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v < 0) return "below Nash";
  if (v < 0.33) return "competitive";
  if (v < 0.67) return "partly cooperative";
  if (v <= 1) return "cooperative";
  return "beyond Pareto";
}

function labelClass(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  return v < 0.33 ? "competitive" : v < 0.67 ? "drifting" : "collusive";
}

/**
 * Semicircle gauge from 0 (competitive / Nash) to 1 (cooperative / Pareto). The needle is
 * clamped to the dial; the number shows the true value (it can be < 0 or > 1).
 */
export function CollusionGauge({
  value,
  history,
  note,
  size = 300,
  title,
}: {
  value: number | null;
  history?: (number | null)[];
  note?: string;
  size?: number;
  title?: string;
}) {
  const gid = useId().replace(/:/g, "");
  const R = 78;
  const cx = 100;
  const cy = 92;
  const ang = Math.PI * (1 - clamp(value ?? 0, 0, 1)); // 180° (Nash) → 0° (Pareto)
  const arc = (a0: number, a1: number) =>
    `M ${cx + R * Math.cos(a0)} ${cy - R * Math.sin(a0)} A ${R} ${R} 0 0 1 ${cx + R * Math.cos(a1)} ${cy - R * Math.sin(a1)}`;
  const off = value != null && (value > 1 || value < 0);
  return (
    <div className="gauge" style={{ maxWidth: size }}>
      {title && <div className="gauge-title">{title}</div>}
      <svg viewBox="0 0 200 116" width="100%">
        <defs>
          <linearGradient id={`g${gid}`} x1="0" x2="1">
            <stop offset="0" stopColor="#2dd4bf" />
            <stop offset="0.5" stopColor="#f5b841" />
            <stop offset="1" stopColor="#f87171" />
          </linearGradient>
        </defs>
        <path d={arc(Math.PI, 0)} stroke="#1c2230" strokeWidth="14" fill="none" strokeLinecap="round" />
        <path d={arc(Math.PI, 0)} stroke={`url(#g${gid})`} strokeWidth="14" fill="none" strokeLinecap="round" opacity={value == null ? 0.25 : 0.9} />
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const a = Math.PI * (1 - f);
          return (
            <line
              key={f}
              x1={cx + (R - 12) * Math.cos(a)}
              y1={cy - (R - 12) * Math.sin(a)}
              x2={cx + (R - 18) * Math.cos(a)}
              y2={cy - (R - 18) * Math.sin(a)}
              stroke="#4b5568"
              strokeWidth="1.5"
            />
          );
        })}
        {value != null && (
          <g className="needle" style={{ transform: `rotate(${(-ang * 180) / Math.PI}deg)`, transformOrigin: `${cx}px ${cy}px` }}>
            <line x1={cx} y1={cy} x2={cx + R - 22} y2={cy} stroke={off ? "#fca5a5" : "#f3f4f6"} strokeWidth="2.5" strokeLinecap="round" />
          </g>
        )}
        <circle cx={cx} cy={cy} r="5" fill="#f3f4f6" />
        <text x={cx - R} y={cy + 18} className="gauge-end" textAnchor="middle">
          0 · Nash
        </text>
        <text x={cx + R} y={cy + 18} className="gauge-end" textAnchor="middle">
          Pareto · 1
        </text>
      </svg>
      <div className="gauge-value mono">
        {value == null ? "—" : value.toFixed(2)}
        {off && <span className="gauge-off">{value! > 1 ? " ▸ off dial" : " ◂ off dial"}</span>}
      </div>
      <div className={`gauge-label ${labelClass(value)}`}>{deltaLabel(value)}</div>
      {history && (
        <div className="gauge-hist">
          {history.map((h, i) => (
            <i key={i} title={h == null ? "" : `E${i}: ${h.toFixed(2)}`} style={{ height: `${6 + clamp(h ?? 0, 0, 1.2) * 20}px`, opacity: h == null ? 0.15 : 1 }} />
          ))}
        </div>
      )}
      {note && <div className="muted small gauge-note">{note}</div>}
    </div>
  );
}
