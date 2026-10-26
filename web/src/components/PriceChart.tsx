import type { Run } from "../types";
import { FONT_MONO, usePlaybackCanvas } from "../lib/canvas";
import { niceStep } from "../lib/format";
import { epochAt, snapIndex } from "../lib/query";

const AXIS_W = 66;
const TOP = 18;
const BOTTOM = 8;
const HEATMAP_WINDOW = 2400;
const HEAD = 0.84;

/** Whole-run price overview for one asset: mid revealed up to the playhead, hidden V dashed. */
export function PriceChart({ run, asset }: { run: Run; asset: string }) {
  const ref = usePlaybackCanvas(
    ({ ctx, w, h }, pb) => {
      const s = run.series[asset];
      if (!s || run.n === 0) return;
      const plotW = w - AXIS_W;
      const plotH = h - TOP - BOTTOM;
      const pad = Math.max((s.hi - s.lo) * 0.08, run.tick * 2);
      const lo = s.lo - pad;
      const hi = s.hi + pad;
      const T = Math.max(1, run.tEnd);
      const xOf = (t: number) => (t / T) * plotW;
      const yOf = (p: number) => TOP + ((hi - p) / (hi - lo)) * plotH;
      const t = pb.t;
      const i1 = snapIndex(run, t);
      const curE = epochAt(run, t);

      // epoch bands + labels
      ctx.font = `600 9.5px ${FONT_MONO}`;
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      for (const ep of run.epochs) {
        const x0 = xOf(ep.t0);
        const x1 = Math.min(plotW, xOf(ep.t1));
        if (x0 >= plotW) break;
        if (ep.epoch % 2 === 1) {
          ctx.fillStyle = "rgba(255,255,255,0.018)";
          ctx.fillRect(x0, TOP, x1 - x0, plotH);
        }
        if (ep.epoch === curE) {
          ctx.fillStyle = "rgba(123,140,255,0.06)";
          ctx.fillRect(x0, TOP, x1 - x0, plotH);
        }
        ctx.fillStyle = ep.epoch === curE ? "rgba(190,198,255,0.95)" : "rgba(140,148,166,0.55)";
        if (x1 - x0 > 26) ctx.fillText(`E${ep.epoch}`, x0 + 5, 4);
      }

      // y axis
      ctx.font = `10px ${FONT_MONO}`;
      ctx.textBaseline = "middle";
      const step = niceStep(hi - lo, 4);
      for (let p = Math.ceil(lo / step) * step; p <= hi; p += step) {
        const y = Math.round(yOf(p)) + 0.5;
        ctx.strokeStyle = "rgba(255,255,255,0.04)";
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(plotW, y);
        ctx.stroke();
        ctx.fillStyle = "rgba(140,148,166,0.7)";
        ctx.fillText(p.toFixed(run.tick < 1 ? 2 : 0), plotW + 8, y);
      }

      // heatmap window bracket
      const win = Math.min(HEATMAP_WINDOW, Math.max(400, run.tEnd));
      const wl = Math.max(0, xOf(t - win * HEAD));
      const wr = xOf(t);
      ctx.fillStyle = "rgba(123,140,255,0.05)";
      ctx.fillRect(wl, TOP, wr - wl, plotH);
      ctx.fillStyle = "rgba(123,140,255,0.5)";
      ctx.fillRect(wl, TOP + plotH - 2, wr - wl, 2);

      // future (faint) and past (bright) mid
      const line = (from: number, to: number) => {
        ctx.beginPath();
        for (let i = from; i <= to; i++) {
          const x = xOf(run.t[i]);
          const y = yOf(s.mid[i]);
          if (i === from) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
      };
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(200,206,220,0.1)";
      line(i1, run.n - 1);
      ctx.stroke();

      line(0, i1);
      ctx.lineTo(xOf(t), yOf(s.mid[i1]));
      const grad = ctx.createLinearGradient(0, TOP, 0, TOP + plotH);
      grad.addColorStop(0, "rgba(123,140,255,0.20)");
      grad.addColorStop(1, "rgba(123,140,255,0)");
      ctx.save();
      ctx.lineTo(xOf(t), TOP + plotH);
      ctx.lineTo(xOf(run.t[0]), TOP + plotH);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.restore();
      line(0, i1);
      ctx.lineTo(xOf(t), yOf(s.mid[i1]));
      ctx.strokeStyle = "#e6e9f2";
      ctx.lineWidth = 1.3;
      ctx.stroke();

      if (pb.showFairValue) {
        ctx.beginPath();
        let open = false;
        for (let i = 0; i <= i1; i++) {
          const v = s.v[i];
          if (!Number.isFinite(v)) {
            open = false;
            continue;
          }
          if (open) ctx.lineTo(xOf(run.t[i]), yOf(v));
          else ctx.moveTo(xOf(run.t[i]), yOf(v));
          open = true;
        }
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = "rgba(255,255,255,0.55)";
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // review markers along the bottom
      for (const d of run.decisions) {
        if (d.t > t) break;
        const a = run.agentById[d.agent];
        ctx.fillStyle = a?.color ?? "#fff";
        ctx.beginPath();
        ctx.arc(xOf(d.t), TOP + plotH - 6 - (a ? (a.index % 4) * 5 : 0), 2, 0, Math.PI * 2);
        ctx.fill();
      }

      // playhead
      const hx = xOf(t);
      const hy = yOf(s.mid[i1]);
      ctx.strokeStyle = "rgba(170,182,255,0.5)";
      ctx.beginPath();
      ctx.moveTo(Math.round(hx) + 0.5, TOP);
      ctx.lineTo(Math.round(hx) + 0.5, TOP + plotH);
      ctx.stroke();
      ctx.fillStyle = "rgba(123,140,255,0.25)";
      ctx.beginPath();
      ctx.arc(hx, hy, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(hx, hy, 2.6, 0, Math.PI * 2);
      ctx.fill();
    },
    [run, asset],
  );
  return <canvas ref={ref} className="fill-canvas" />;
}
