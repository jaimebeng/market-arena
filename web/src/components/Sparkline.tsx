import { useMemo } from "react";
import type { AgentView, Run } from "../types";
import { hexA, usePlaybackCanvas } from "../lib/canvas";
import { snapIndex } from "../lib/query";

/** Per-snapshot P&L for an agent: snapshot equity, or a step series from epoch metrics. */
export function pnlSeries(run: Run, id: string): Float64Array {
  const eq = run.equity[id];
  if (eq) return eq;
  const out = new Float64Array(run.n).fill(0);
  let k = 0;
  let cur = 0;
  for (let i = 0; i < run.n; i++) {
    while (k < run.metrics.length && run.metrics[k].t1 <= run.t[i] + run.dtSnap) {
      cur = run.metrics[k].agents[id]?.equity ?? cur;
      k++;
    }
    out[i] = cur;
  }
  return out;
}

/** P&L sparkline over the whole run domain, drawn up to the playhead. */
export function Sparkline({ run, agent }: { run: Run; agent: AgentView }) {
  const series = useMemo(() => {
    const s = pnlSeries(run, agent.id);
    let lo = 0;
    let hi = 0;
    for (const v of s) {
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    return { s, lo, hi };
  }, [run, agent.id]);

  const ref = usePlaybackCanvas(
    ({ ctx, w, h }, pb) => {
      const { s, lo, hi } = series;
      const pad = 3;
      const span = Math.max(1, hi - lo);
      const xOf = (t: number) => (t / Math.max(1, run.tEnd)) * (w - 4);
      const yOf = (v: number) => pad + ((hi - v) / span) * (h - pad * 2);
      const i1 = snapIndex(run, pb.t);
      const y0 = yOf(0);

      // zero line
      ctx.strokeStyle = "rgba(255,255,255,0.08)";
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(0, Math.round(y0) + 0.5);
      ctx.lineTo(w, Math.round(y0) + 0.5);
      ctx.stroke();
      ctx.setLineDash([]);

      // epoch ticks
      ctx.fillStyle = "rgba(255,255,255,0.07)";
      for (const ep of run.epochs) if (ep.t0 > 0 && ep.t0 < run.tEnd) ctx.fillRect(Math.round(xOf(ep.t0)), h - 3, 1, 3);

      ctx.beginPath();
      let started = false;
      for (let i = 0; i <= i1; i++) {
        const v = s[i];
        if (!Number.isFinite(v)) continue;
        const x = xOf(run.t[i]);
        if (!started) {
          ctx.moveTo(x, yOf(v));
          started = true;
        } else ctx.lineTo(x, yOf(v));
      }
      if (!started) return;
      const lastX = xOf(run.t[i1]);
      ctx.strokeStyle = agent.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.lineTo(lastX, y0);
      ctx.lineTo(xOf(run.t[0]), y0);
      ctx.closePath();
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, hexA(agent.color, 0.28));
      g.addColorStop(1, hexA(agent.color, 0.02));
      ctx.fillStyle = g;
      ctx.fill();

      const v = s[i1];
      if (Number.isFinite(v)) {
        ctx.fillStyle = agent.color;
        ctx.beginPath();
        ctx.arc(lastX, yOf(v), 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
    },
    [series],
  );
  return <canvas ref={ref} className="sparkline" />;
}
