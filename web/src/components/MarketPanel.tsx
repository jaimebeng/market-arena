import { useRef } from "react";
import type { Run } from "../types";
import { BUY, SELL } from "../lib/agents";
import { useFrame, useUi } from "../lib/playback";
import { snapIndex } from "../lib/query";
import { BookHeatmap } from "./BookHeatmap";
import { PriceChart } from "./PriceChart";

function AssetChip({ run, asset, active, onClick }: { run: Run; asset: string; active: boolean; onClick: () => void }) {
  const px = useRef<HTMLSpanElement>(null);
  const ch = useRef<HTMLSpanElement>(null);
  useFrame((pb, dirty) => {
    if (!dirty || !px.current || !ch.current) return;
    const s = run.series[asset];
    const i = snapIndex(run, pb.t);
    const m = s.mid[i];
    const r = ((m - s.mid[0]) / s.mid[0]) * 1e4;
    px.current.textContent = m.toFixed(run.tick < 1 ? 2 : 1);
    ch.current.textContent = `${r >= 0 ? "+" : "−"}${Math.abs(r).toFixed(1)}bp`;
    ch.current.style.color = r >= 0 ? BUY : SELL;
  });
  return (
    <button className={`asset-chip ${active ? "active" : ""}`} onClick={onClick}>
      <span className="asset-name">{asset}</span>
      <span className="mono" ref={px} />
      <span className="mono small" ref={ch} />
    </button>
  );
}

export function MarketPanel({ run, asset, onAsset }: { run: Run; asset: string; onAsset: (a: string) => void }) {
  const pb = useUi((p) => p.showFairValue);
  return (
    <section className="panel market-panel">
      <div className="panel-head">
        <div className="panel-title">
          Market
          <span className="panel-sub">order book · quotes · trades</span>
        </div>
        <div className="asset-chips">
          {run.assets.map((a) => (
            <AssetChip key={a} run={run} asset={a} active={a === asset} onClick={() => onAsset(a)} />
          ))}
        </div>
        <div className="legend">
          {run.makers.map((m) => (
            <span key={m.id} className="legend-item">
              <i className="swatch-line" style={{ background: m.color }} />
              {m.id}
            </span>
          ))}
          <span className="legend-item">
            <i className="dot" style={{ background: BUY }} />
            buy
          </span>
          <span className="legend-item">
            <i className="dot" style={{ background: SELL }} />
            sell
          </span>
          <button
            className={`toggle ${pb.showFairValue ? "on" : ""}`}
            title="Hidden fair value V (agents never see it) — key: V"
            onClick={() => {
              pb.showFairValue = !pb.showFairValue;
              pb.invalidate();
            }}
          >
            <i className="swatch-dash" /> fair value V
          </button>
        </div>
      </div>
      <div className="price-wrap">
        <PriceChart run={run} asset={asset} />
      </div>
      <div className="heatmap-wrap">
        <BookHeatmap run={run} asset={asset} />
        <div className="heatmap-key">
          <span>resting depth</span>
          <i className="ramp bid" />
          <span>bid</span>
          <i className="ramp ask" />
          <span>ask</span>
        </div>
      </div>
    </section>
  );
}
