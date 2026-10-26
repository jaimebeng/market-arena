import { useRef } from "react";
import type { Run } from "../types";
import { useFrame, useUi } from "../lib/playback";
import { epochAt } from "../lib/query";
import { upperIndex } from "../lib/format";

/** Epoch scrubber: segments per epoch, review markers per agent, draggable playhead. */
export function Timeline({ run }: { run: Run }) {
  const pb = useUi((p) => `${epochAt(run, p.t)}:${upperIndex(run.reviewTimes, p.t)}`);
  const track = useRef<HTMLDivElement>(null);
  const fill = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const T = Math.max(1, run.tEnd);
  const cur = epochAt(run, pb.t);

  useFrame((p, dirty) => {
    if (!dirty) return;
    const f = (p.t / T) * 100;
    if (fill.current) fill.current.style.width = `${f}%`;
    if (head.current) head.current.style.left = `${f}%`;
  });

  const seekFromEvent = (clientX: number) => {
    const el = track.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    pb.seek(((clientX - r.left) / r.width) * T);
  };

  const byT = new Map<number, string[]>();
  for (const d of run.decisions) byT.set(d.t, [...(byT.get(d.t) ?? []), d.agent]);

  return (
    <div className="timeline">
      <div
        className="tl-track"
        ref={track}
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          seekFromEvent(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.buttons & 1) seekFromEvent(e.clientX);
        }}
      >
        {run.epochs.map((ep) => {
          const l = (ep.t0 / T) * 100;
          const w = ((Math.min(ep.t1, T) - ep.t0) / T) * 100;
          if (w <= 0) return null;
          return (
            <div key={ep.epoch} className={`tl-epoch ${ep.epoch === cur ? "cur" : ""} ${ep.t1 <= pb.t ? "done" : ""}`} style={{ left: `${l}%`, width: `${w}%` }}>
              <span>E{ep.epoch}</span>
            </div>
          );
        })}
        <div className="tl-fill" ref={fill} />
        {[...byT.entries()].map(([t, agents]) => (
          <div key={t} className={`tl-review ${t <= pb.t ? "past" : ""}`} style={{ left: `${(t / T) * 100}%` }} title={`review at t=${t}: ${agents.join(", ")}`}>
            {agents.map((id, k) => (
              <i key={k} style={{ background: run.agentById[id]?.color }} />
            ))}
          </div>
        ))}
        <div className="tl-head" ref={head} />
      </div>
    </div>
  );
}
