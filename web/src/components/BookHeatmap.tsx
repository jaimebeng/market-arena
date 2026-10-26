import { useMemo, useRef } from "react";
import type { Run } from "../types";
import { BUY, BUY_RGB, SELL, SELL_RGB } from "../lib/agents";
import { FONT_MONO, hexA, usePlaybackCanvas } from "../lib/canvas";
import { lowerIndex, niceStep, upperIndex } from "../lib/format";
import { snapIndex } from "../lib/query";

const WINDOW_STEPS = 2400; // visible history
const HEAD = 0.84; // playhead position (fraction of plot width)
const AXIS_W = 66;
const TOP = 20;
const BOTTOM = 20;
const BG: [number, number, number] = [12, 15, 21];

/** 256-entry colour ramp per side: dark tint → saturated → hot white. */
function makeLut(rgb: [number, number, number]): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const x = i / 255;
    const k = 0.16 + 0.84 * Math.pow(x, 0.75);
    const hot = Math.max(0, (x - 0.72) / 0.28) * 0.55;
    for (let c = 0; c < 3; c++) {
      const base = BG[c] + (rgb[c] - BG[c]) * k;
      lut[i * 3 + c] = base + (255 - base) * hot;
    }
  }
  return lut;
}
const BID_LUT = makeLut(BUY_RGB);
const ASK_LUT = makeLut(SELL_RGB);

/**
 * Order-book depth heatmap (time × price, intensity = resting qty) for one asset, with each
 * maker's quotes as coloured lines, trades as dots and the hidden fair value as a dashed line.
 * Rendered per frame into a small offscreen bitmap (cols = snapshots, rows = ticks) that is
 * scaled onto the canvas, so cost is O(visible snapshots × levels).
 */
export function BookHeatmap({ run, asset }: { run: Run; asset: string }) {
  const view = useRef({ center: NaN, half: NaN, key: "" });
  const off = useMemo(() => {
    const c = document.createElement("canvas");
    return { c, ctx: c.getContext("2d")!, img: null as ImageData | null };
  }, []);

  const ref = usePlaybackCanvas(
    ({ ctx, w, h }, pb) => {
      const s = run.series[asset];
      if (!s || run.n === 0) return;
      const tick = run.tick;
      const plotW = w - AXIS_W;
      const plotH = h - TOP - BOTTOM;
      const win = Math.min(WINDOW_STEPS, Math.max(400, run.tEnd));
      const t = pb.t;
      const tLeft = t - win * HEAD;
      const xOf = (tt: number) => ((tt - tLeft) / win) * plotW;
      const headX = xOf(t);
      const i1 = snapIndex(run, t);
      const i0 = Math.max(0, upperIndex(run.t, tLeft));

      // ---- vertical range: follow the mid with easing ---------------------------------------
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = i0; i <= i1; i++) {
        const m = s.mid[i];
        if (m < lo) lo = m;
        if (m > hi) hi = m;
        if (pb.showFairValue) {
          const fv = s.v[i];
          if (fv < lo) lo = fv;
          if (fv > hi) hi = fv;
        }
      }
      if (!Number.isFinite(lo)) {
        lo = s.lo;
        hi = s.hi;
      }
      const tCenter = (lo + hi) / 2;
      const tHalf = Math.max(16 * tick, (hi - lo) / 2 + 9 * tick);
      const v = view.current;
      const key = run.name + asset;
      let animating = false;
      if (v.key !== key || !Number.isFinite(v.center) || Math.abs(tCenter - v.center) > tHalf * 3) {
        v.center = tCenter;
        v.half = tHalf;
        v.key = key;
      } else {
        v.center += (tCenter - v.center) * 0.12;
        v.half += (tHalf - v.half) * 0.08;
        animating = Math.abs(tCenter - v.center) > tick * 0.02 || Math.abs(tHalf - v.half) > tick * 0.02;
      }
      const pTop = v.center + v.half;
      const pBot = v.center - v.half;
      const yOf = (p: number) => TOP + ((pTop - p) / (pTop - pBot)) * plotH;

      // ---- heatmap bitmap ---------------------------------------------------------------------
      const pHi = Math.ceil(pTop / tick) * tick;
      const pLo = Math.floor(pBot / tick) * tick;
      const rows = Math.round((pHi - pLo) / tick) + 1;
      const cols = i1 - i0 + 1;
      if (cols > 0 && rows > 0 && rows < 4000) {
        if (!off.img || off.img.width !== cols || off.img.height !== rows) {
          off.c.width = Math.max(off.c.width, cols);
          off.c.height = Math.max(off.c.height, rows);
          off.img = off.ctx.createImageData(cols, rows);
        }
        const data = off.img.data;
        data.fill(0);
        const L = s.L;
        const qRef = s.qRef;
        for (let c = 0; c < cols; c++) {
          const i = i0 + c;
          const base = s.base[i];
          for (let side = 0; side < 2; side++) {
            const P = side === 0 ? s.bp : s.ap;
            const Q = side === 0 ? s.bq : s.aq;
            const lut = side === 0 ? BID_LUT : ASK_LUT;
            for (let k = 0; k < L; k++) {
              const q = Q[i * L + k];
              if (q <= 0) continue;
              const px = base + P[i * L + k];
              const row = rows - 1 - Math.round((px - pLo) / tick);
              if (row < 0 || row >= rows) continue;
              const li = Math.min(255, Math.round(Math.sqrt(q / qRef) * 255)) * 3;
              const o = (row * cols + c) * 4;
              data[o] = lut[li];
              data[o + 1] = lut[li + 1];
              data[o + 2] = lut[li + 2];
              data[o + 3] = 255;
            }
          }
        }
        off.ctx.putImageData(off.img, 0, 0);
        const dx = xOf(run.t[i0]);
        const dw = xOf(run.t[i1] + run.dtSnap) - dx;
        const dy = yOf(pHi + tick / 2);
        const dh = yOf(pLo - tick / 2) - dy;
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, TOP, headX, plotH);
        ctx.clip();
        ctx.imageSmoothingEnabled = false;
        ctx.globalAlpha = 0.92;
        ctx.drawImage(off.c, 0, 0, cols, rows, dx, dy, dw, dh);
        ctx.globalAlpha = 1;
        ctx.restore();
      }

      // ---- grid + price axis --------------------------------------------------------------------
      ctx.font = `10.5px ${FONT_MONO}`;
      ctx.textBaseline = "middle";
      const step = Math.max(tick, niceStep(pTop - pBot, 7));
      ctx.strokeStyle = "rgba(255,255,255,0.045)";
      ctx.lineWidth = 1;
      ctx.fillStyle = "rgba(160,168,186,0.75)";
      ctx.textAlign = "left";
      for (let p = Math.ceil(pBot / step) * step; p <= pTop; p += step) {
        const y = Math.round(yOf(p)) + 0.5;
        if (y < TOP + 6 || y > TOP + plotH - 6) continue;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(plotW, y);
        ctx.stroke();
        ctx.fillText(p.toFixed(tick < 1 ? 2 : 0), plotW + 8, y);
      }

      // ---- epochs & review markers ----------------------------------------------------------
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, plotW, h);
      ctx.clip();
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.font = `600 9.5px ${FONT_MONO}`;
      for (const ep of run.epochs) {
        const x = xOf(ep.t0);
        if (x < -80 || x > headX) continue;
        ctx.strokeStyle = "rgba(255,255,255,0.16)";
        ctx.setLineDash([2, 4]);
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, TOP);
        ctx.lineTo(Math.round(x) + 0.5, TOP + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(200,206,220,0.55)";
        ctx.fillText(`EPOCH ${ep.epoch}`, x + 5, 5);
      }
      for (const rt of run.reviewTimes) {
        const x = xOf(rt);
        if (x < -10 || x > headX + 1) continue;
        const ds = run.decisions.filter((d) => d.t === rt);
        ds.forEach((d, j) => {
          const a = run.agentById[d.agent];
          ctx.fillStyle = a?.color ?? "#fff";
          ctx.beginPath();
          const cx = x - 3 - j * 8;
          ctx.moveTo(cx, TOP - 6);
          ctx.lineTo(cx + 3.2, TOP - 2.5);
          ctx.lineTo(cx, TOP + 1);
          ctx.lineTo(cx - 3.2, TOP - 2.5);
          ctx.fill();
        });
      }
      ctx.restore();

      // clip overlays to the past
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, TOP, headX, plotH);
      ctx.clip();

      // ---- mid ----------------------------------------------------------------------------------
      ctx.strokeStyle = "rgba(235,238,245,0.5)";
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      for (let i = i0; i <= i1; i++) {
        const x = xOf(run.t[i]);
        const y = yOf(s.mid[i]);
        if (i === i0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.lineTo(headX, yOf(s.mid[i1]));
      ctx.stroke();

      // ---- maker quotes ---------------------------------------------------------------------
      const makers = run.makers.filter((m) => run.quotes[m.id]?.[asset]);
      for (const pass of [0, 1]) {
        for (const m of makers) {
          const q = run.quotes[m.id][asset];
          ctx.strokeStyle = pass === 0 ? hexA(m.color, 0.16) : m.color;
          ctx.lineWidth = pass === 0 ? 5 : 1.5;
          for (const arr of [q.b, q.a]) {
            ctx.beginPath();
            let open = false;
            for (let i = i0; i <= i1; i++) {
              const p = arr[i];
              if (!Number.isFinite(p)) {
                open = false;
                continue;
              }
              const x0 = xOf(run.t[i]);
              const x1 = i === i1 ? headX : xOf(run.t[i + 1]);
              const y = yOf(p);
              if (open) ctx.lineTo(x0, y);
              else ctx.moveTo(x0, y);
              ctx.lineTo(x1, y);
              open = true;
            }
            ctx.stroke();
          }
        }
      }

      // ---- hidden fair value --------------------------------------------------------------------
      if (pb.showFairValue) {
        ctx.strokeStyle = "rgba(255,255,255,0.9)";
        ctx.lineWidth = 1.4;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        let open = false;
        for (let i = i0; i <= i1; i++) {
          const val = s.v[i];
          if (!Number.isFinite(val)) {
            open = false;
            continue;
          }
          const x = xOf(run.t[i]);
          if (open) ctx.lineTo(x, yOf(val));
          else ctx.moveTo(x, yOf(val));
          open = true;
        }
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // ---- trades -----------------------------------------------------------------------------
      const tr = run.trades[asset];
      if (tr && tr.t.length) {
        const j0 = lowerIndex(tr.t, tLeft);
        const j1 = upperIndex(tr.t, t);
        for (const side of [1, -1]) {
          ctx.fillStyle = hexA(side > 0 ? BUY : SELL, 0.8);
          ctx.beginPath();
          for (let j = j0; j <= j1; j++) {
            if (tr.s[j] !== side) continue;
            const x = xOf(tr.t[j]);
            const y = yOf(tr.px[j]);
            const r = 1.3 + Math.sqrt(tr.q[j]) * 0.9;
            ctx.moveTo(x + r, y);
            ctx.arc(x, y, r, 0, Math.PI * 2);
          }
          ctx.fill();
        }
        // trades involving an agent: ring in the agent colour; fresh ones ping
        ctx.lineWidth = 1.3;
        for (let j = j0; j <= j1; j++) {
          const ai = tr.mk[j] >= 0 ? tr.mk[j] : tr.tk[j];
          if (ai < 0) continue;
          const a = run.agents[ai];
          const x = xOf(tr.t[j]);
          const y = yOf(tr.px[j]);
          const r = 2.6 + Math.sqrt(tr.q[j]) * 1.0;
          const age = t - tr.t[j];
          ctx.strokeStyle = a.color;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.stroke();
          if (age < 60) {
            const k = age / 60;
            ctx.strokeStyle = hexA(a.color, 0.7 * (1 - k));
            ctx.beginPath();
            ctx.arc(x, y, r + 2 + k * 12, 0, Math.PI * 2);
            ctx.stroke();
          }
        }
      }
      ctx.restore();

      // ---- future shade + playhead ----------------------------------------------------------
      const g = ctx.createLinearGradient(headX, 0, plotW, 0);
      g.addColorStop(0, "rgba(123,140,255,0.06)");
      g.addColorStop(1, "rgba(123,140,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(headX, TOP, plotW - headX, plotH);
      ctx.strokeStyle = "rgba(170,182,255,0.55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.round(headX) + 0.5, TOP);
      ctx.lineTo(Math.round(headX) + 0.5, TOP + plotH);
      ctx.stroke();

      // current quote ladder just right of the playhead (one lane per maker)
      makers.forEach((m, k) => {
        const q = run.quotes[m.id][asset];
        const x = headX + 5 + k * 9;
        for (const p of [q.b[i1], q.a[i1]]) {
          if (!Number.isFinite(p)) continue;
          const y = yOf(p);
          ctx.fillStyle = m.color;
          ctx.fillRect(x, y - 1.5, 7, 3);
        }
        const b = q.b[i1];
        const a = q.a[i1];
        if (Number.isFinite(b) && Number.isFinite(a)) {
          ctx.strokeStyle = hexA(m.color, 0.45);
          ctx.beginPath();
          ctx.moveTo(x + 3.5, yOf(a));
          ctx.lineTo(x + 3.5, yOf(b));
          ctx.stroke();
        }
      });

      // price pills on the axis
      const pill = (p: number, fg: string, bg: string, dashed = false) => {
        const y = yOf(p);
        if (y < TOP || y > TOP + plotH) return;
        ctx.font = `600 10.5px ${FONT_MONO}`;
        const txt = p.toFixed(tick < 1 ? 2 : 1);
        const tw = ctx.measureText(txt).width + 10;
        ctx.fillStyle = bg;
        ctx.strokeStyle = fg;
        ctx.setLineDash(dashed ? [3, 2] : []);
        ctx.beginPath();
        ctx.roundRect(plotW + 3, y - 8, tw, 16, 3);
        ctx.fill();
        if (dashed) ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = fg;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(txt, plotW + 8, y + 0.5);
      };
      if (pb.showFairValue && Number.isFinite(s.v[i1])) pill(s.v[i1], "#ffffff", "rgba(12,15,21,0.95)", true);
      pill(s.mid[i1], "#0b0d12", "#e8ebf2");

      // ---- time axis ----------------------------------------------------------------------------
      ctx.font = `10px ${FONT_MONO}`;
      ctx.fillStyle = "rgba(140,148,166,0.7)";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const ts = niceStep(win, 6);
      for (let tt = Math.ceil(Math.max(0, tLeft) / ts) * ts; tt <= t; tt += ts) {
        const x = xOf(tt);
        if (x < 20 || x > headX - 20) continue;
        ctx.fillText(`t ${tt.toLocaleString("en-US")}`, x, TOP + plotH + 5);
      }
      ctx.fillStyle = "rgba(190,198,255,0.9)";
      ctx.fillText(`t ${Math.round(t).toLocaleString("en-US")}`, headX, TOP + plotH + 5);

      return animating;
    },
    [run, asset],
  );

  return <canvas ref={ref} className="fill-canvas" />;
}
