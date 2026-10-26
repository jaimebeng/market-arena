import type { Run } from "../../types";
import { ASSET_COLORS } from "../../lib/agents";
import { fmtCompact, fmtNum } from "../../lib/format";
import { useUi } from "../../lib/playback";
import { completedMetrics } from "../../lib/query";
import { ChartLegend, EpochChart, type ChartSeries } from "../charts/EpochChart";
import { StylizedPanel } from "../StylizedPanel";

const METRICS: { key: string; title: string; unit: string; hint: string }[] = [
  { key: "spread", title: "Quoted spread", unit: "ticks", hint: "average best ask − best bid; lower is better for traders" },
  { key: "depth", title: "Top-5 depth", unit: "lots", hint: "resting size within 5 levels; higher is more liquid" },
  { key: "mispricing_bps", title: "Mispricing |mid − V|", unit: "bps", hint: "distance from hidden fair value; price efficiency" },
  { key: "vol_per_step", title: "Volatility", unit: "ticks/step", hint: "std of mid changes per step" },
  { key: "volume", title: "Volume", unit: "lots", hint: "traded volume per epoch" },
];

export function MarketQualityTab({ run, asset }: { run: Run; asset: string }) {
  const styAsset = run.stylized?.[asset] ? asset : Object.keys(run.stylized ?? {})[0];
  const sty = styAsset ? run.stylized?.[styAsset] : undefined;
  const pb = useUi((p) => completedMetrics(run, p.t).length);
  const done = completedMetrics(run, pb.t);
  const revealed = done.length;
  const n = Math.max(run.metrics.length, run.epochs.length);
  const colors = Object.fromEntries(run.assets.map((a, i) => [a, ASSET_COLORS[i % ASSET_COLORS.length]]));
  const stylized = [...done].reverse().find((m) => m.stylized)?.stylized;

  return (
    <div>
      {run.assets.length > 1 && <ChartLegend series={run.assets.map((a) => ({ label: a, color: colors[a] }))} />}
      <div className="mq-grid">
        {METRICS.map((m) => {
          const series: ChartSeries[] = run.assets.map((a) => ({
            key: a,
            label: a,
            color: colors[a],
            values: run.metrics.map((x) => x.market[a]?.[m.key] ?? null),
          }));
          const last = done.length ? done[done.length - 1].market : undefined;
          return (
            <div className="mq-card" key={m.key} title={m.hint}>
              <div className="card-title">
                {m.title} <span className="muted">· {m.unit}</span>
                <span className="spacer" />
                <span className="mono mq-last">{last ? fmtCompact(last[run.assets[0]]?.[m.key]) : "—"}</span>
              </div>
              <EpochChart series={series} nEpochs={n} revealed={revealed} height={150} format={(v) => fmtCompact(v)} />
            </div>
          );
        })}
        <div className="mq-card">
          <div className="card-title">
            Stylised facts <span className="muted">· {sty ? `${styAsset}, whole run` : "per epoch"}</span>
          </div>
          {sty ? (
            <StylizedPanel market={sty.market} fv={sty.fair_value} />
          ) : stylized ? (
            <table className="stylized">
              <thead>
                <tr>
                  <th />
                  {run.assets.filter((a) => stylized[a]).map((a) => (
                    <th key={a}>{a}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...new Set(Object.values(stylized).flatMap((o) => Object.keys(o)))].map((k) => (
                  <tr key={k}>
                    <td className="muted">{k.replace(/_/g, " ")}</td>
                    {run.assets.filter((a) => stylized[a]).map((a) => (
                      <td key={a} className="mono">
                        {fmtNum(stylized[a][k], 2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty small muted">Fat tails, volatility clustering and return autocorrelation appear here when the run logs <code>stylized</code>.</div>
          )}
        </div>
      </div>
    </div>
  );
}
