import type { StylizedFacts } from "../types";
import { fmtNum } from "../lib/format";

function AcfBars({ values, color, title, hint }: { values: number[]; color: string; title: string; hint: string }) {
  const W = 260;
  const H = 92;
  const pad = 4;
  const m = Math.max(0.1, ...values.map((v) => Math.abs(v))) * 1.1;
  const bw = (W - pad * 2) / values.length;
  const y0 = H / 2;
  return (
    <div className="acf" title={hint}>
      <div className="acf-title">
        {title} <span className="muted">· {values.length} lags</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="none">
        <line x1={0} x2={W} y1={y0} y2={y0} stroke="rgba(255,255,255,0.18)" />
        {values.map((v, i) => {
          const h = (Math.abs(v) / m) * (H / 2 - 2);
          return <rect key={i} x={pad + i * bw + bw * 0.15} width={bw * 0.7} y={v >= 0 ? y0 - h : y0} height={Math.max(0.5, h)} fill={color} opacity={0.85} />;
        })}
      </svg>
      <div className="acf-axis muted">
        <span>lag 1</span>
        <span>±{m.toFixed(2)}</span>
        <span>lag {values.length}</span>
      </div>
    </div>
  );
}

function HillScale({ market, fv }: { market?: number; fv?: number }) {
  const lo = 1;
  const hi = 6;
  const pos = (x: number) => `${((Math.min(hi, Math.max(lo, x)) - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="hill">
      <div className="hill-track">
        <i className="hill-real" style={{ left: pos(3) }} title="real markets ≈ 3 (inverse cubic law)" />
        {fv != null && <i className="hill-mark fv" style={{ left: pos(fv) }} title={`fair value V: ${fv.toFixed(2)}`} />}
        {market != null && <i className="hill-mark mkt" style={{ left: pos(market) }} title={`market mid: ${market.toFixed(2)}`} />}
      </div>
      <div className="hill-axis muted">
        <span>1 · fat</span>
        <span>real markets ≈ 3</span>
        <span>6 · thin</span>
      </div>
    </div>
  );
}

/** Compact stylised-facts panel: ACF of returns vs |returns|, excess kurtosis, Hill tail index. */
export function StylizedPanel({ market, fv }: { market?: StylizedFacts; fv?: StylizedFacts }) {
  if (!market) return null;
  return (
    <div className="stylized-panel">
      <div className="sty-stats">
        <div className="sty-stat">
          <label>excess kurtosis</label>
          <span className="mono">{fmtNum(market.excess_kurtosis, 2)}</span>
          <small className="muted">V {fmtNum(fv?.excess_kurtosis, 1)} · normal = 0</small>
        </div>
        <div className="sty-stat wide">
          <label>Hill tail index</label>
          <span className="mono">{fmtNum(market.hill_tail_index, 2)}</span>
          <HillScale market={market.hill_tail_index} fv={fv?.hill_tail_index} />
        </div>
      </div>
      <div className="acf-row">
        {market.acf_returns && (
          <AcfBars values={market.acf_returns} color="#93c5fd" title="ACF returns" hint="Returns should be close to uncorrelated (no free lunch)" />
        )}
        {market.acf_abs_returns && (
          <AcfBars values={market.acf_abs_returns} color="#f5b841" title="ACF |returns|" hint="Volatility clustering: |returns| stay positively correlated for many lags in real markets" />
        )}
      </div>
      {market.horizon_steps && <div className="muted small">returns over {market.horizon_steps}-step horizons, traded mid (V = hidden fair value)</div>}
    </div>
  );
}
