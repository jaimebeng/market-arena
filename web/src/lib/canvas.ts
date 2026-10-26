import { useEffect, useRef } from "react";
import { playback, useFrame, type Playback } from "./playback";

export interface CanvasCtx {
  ctx: CanvasRenderingContext2D;
  w: number; // css px
  h: number;
  dpr: number;
}

/**
 * A canvas redrawn from the shared rAF loop. `draw` runs when the playback clock moved,
 * the element resized, or any of `deps` changed.
 */
export function usePlaybackCanvas(
  draw: (c: CanvasCtx, pb: Playback) => boolean | void,
  deps: unknown[] = [],
) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const size = useRef({ w: 0, h: 0, dpr: 1 });
  const needs = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      size.current = { w: r.width, h: r.height, dpr };
      el.width = Math.max(1, Math.round(r.width * dpr));
      el.height = Math.max(1, Math.round(r.height * dpr));
      needs.current = true;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    needs.current = true;
  }, deps);

  useFrame((pb, dirty) => {
    const el = ref.current;
    if (!el || (!dirty && !needs.current)) return;
    const { w, h, dpr } = size.current;
    if (w < 2 || h < 2) return;
    needs.current = false;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    // a draw that returns true is still animating (e.g. easing) and wants another frame
    if (draw({ ctx, w, h, dpr }, pb) === true) needs.current = true;
  });

  return ref;
}

export function forceRedraw() {
  playback.invalidate();
}

export const FONT_MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace';
export const FONT_SANS = 'Inter, ui-sans-serif, system-ui, sans-serif';

export function hexA(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
