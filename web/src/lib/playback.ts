import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Run } from "../types";
import { epochAt } from "./query";

/** Steps per second at 1× speed. */
export const BASE_STEPS_PER_SEC = 40;
export const SPEEDS = [1, 2, 5, 10, 25, 50];
export const TYPE_CHARS_PER_SEC = 120;

type FrameFn = (pb: Playback, dirty: boolean) => void;

/**
 * Replay clock. One requestAnimationFrame loop drives every canvas through `onFrame`
 * listeners (no React renders at 60fps). React components that show discrete state
 * (epoch, policies, play button) subscribe through `useUi`, which is throttled.
 */
export class Playback {
  run: Run | null = null;
  t = 0;
  playing = false;
  speed = 10;
  holdOnReviews = true;
  showFairValue = true;
  holdUntil = 0;
  holdingAt: number | null = null;
  version = 0;

  private frameFns = new Set<FrameFn>();
  private uiFns = new Set<() => void>();
  private raf = 0;
  private lastNow = 0;
  private lastUi = 0;
  private lastEpoch = -1;
  private dirty = true;

  setRun(run: Run) {
    this.run = run;
    this.t = 0;
    this.holdUntil = 0;
    this.holdingAt = null;
    this.lastEpoch = -1;
    this.invalidate();
  }

  start() {
    if (this.raf) return;
    const loop = (now: number) => {
      this.tick(now);
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private tick(now: number) {
    const dt = this.lastNow ? Math.min(0.1, (now - this.lastNow) / 1000) : 0;
    this.lastNow = now;
    const run = this.run;
    let uiNow = false;
    if (run && this.playing) {
      if (now < this.holdUntil) {
        // holding on a review: clock frozen while thought bubbles type out
      } else {
        if (this.holdingAt !== null) {
          this.holdingAt = null;
          uiNow = true;
        }
        let next = this.t + dt * BASE_STEPS_PER_SEC * this.speed;
        if (this.holdOnReviews) {
          const rt = run.reviewTimes.find((x) => x > this.t && x <= next);
          if (rt !== undefined) {
            next = rt;
            this.holdUntil = now + this.holdMs(rt);
            this.holdingAt = rt;
            uiNow = true;
          }
        }
        if (next >= run.tEnd) {
          next = run.tEnd;
          this.playing = false;
          uiNow = true;
        }
        if (next !== this.t) {
          this.t = next;
          this.dirty = true;
        }
      }
    }
    if (run) {
      const e = epochAt(run, this.t);
      if (e !== this.lastEpoch) {
        this.lastEpoch = e;
        uiNow = true;
      }
    }
    const dirty = this.dirty;
    this.dirty = false;
    for (const fn of this.frameFns) fn(this, dirty);
    if (uiNow || (dirty && now - this.lastUi > 90)) {
      this.lastUi = now;
      this.emitUi();
    }
  }

  private holdMs(rt: number): number {
    const run = this.run!;
    const ds = run.decisions.filter((d) => d.t === rt);
    const longest = Math.max(
      0,
      ...ds.map((d) => (d.role === "maker" ? d.rationale?.length ?? 0 : d.hypothesis?.length ?? 0)),
    );
    // enough time to type the longest rationale, then a beat to read it
    return Math.min(9000, Math.max(2500, (longest / TYPE_CHARS_PER_SEC) * 1000 + 1800));
  }

  private emitUi() {
    this.version++;
    for (const fn of this.uiFns) fn();
  }

  invalidate() {
    this.dirty = true;
    this.emitUi();
  }

  seek(t: number) {
    if (!this.run) return;
    this.t = Math.max(0, Math.min(this.run.tEnd, t));
    this.holdUntil = 0;
    this.holdingAt = null;
    this.invalidate();
  }

  play() {
    if (!this.run) return;
    if (this.t >= this.run.tEnd) this.t = 0;
    this.playing = true;
    this.invalidate();
  }

  pause() {
    this.playing = false;
    this.holdUntil = 0;
    this.holdingAt = null;
    this.invalidate();
  }

  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }

  setSpeed(s: number) {
    this.speed = s;
    this.invalidate();
  }

  skipHold() {
    this.holdUntil = 0;
  }

  stepEpoch(dir: 1 | -1) {
    const run = this.run;
    if (!run) return;
    const e = epochAt(run, this.t);
    const target = dir > 0 ? run.epochs[e + 1]?.t0 ?? run.tEnd : this.t - run.epochs[e].t0 > run.dtSnap * 3 ? run.epochs[e].t0 : run.epochs[Math.max(0, e - 1)].t0;
    this.seek(target);
  }

  onFrame(fn: FrameFn) {
    this.frameFns.add(fn);
    this.dirty = true;
    return () => {
      this.frameFns.delete(fn);
    };
  }

  subscribeUi = (fn: () => void) => {
    this.uiFns.add(fn);
    return () => {
      this.uiFns.delete(fn);
    };
  };

  getVersion = () => this.version;
}

export const playback = new Playback();

/** Re-render on throttled playback changes (~11Hz while playing, immediately on discrete events). */
export function useUi(): Playback {
  useSyncExternalStore(playback.subscribeUi, playback.getVersion);
  return playback;
}

/** Register a per-frame callback (runs inside the shared rAF loop). */
export function useFrame(fn: FrameFn) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => playback.onFrame((pb, dirty) => ref.current(pb, dirty)), []);
}
