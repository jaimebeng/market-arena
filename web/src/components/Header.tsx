import type { ModelKind, Run, RunIndexEntry } from "../types";
import { fmtUsd } from "../lib/format";
import { useRef } from "react";
import { SPEEDS, useFrame, useUi } from "../lib/playback";
import { epochAt } from "../lib/query";
import { ModelBadge } from "./ModelBadge";

function Icon({ name }: { name: "play" | "pause" | "prev" | "next" | "restart" }) {
  const p = {
    play: <path d="M4 2.5v11l9.5-5.5z" fill="currentColor" />,
    pause: (
      <>
        <rect x="3.5" y="2.5" width="3.2" height="11" rx="0.8" fill="currentColor" />
        <rect x="9.3" y="2.5" width="3.2" height="11" rx="0.8" fill="currentColor" />
      </>
    ),
    prev: <path d="M3 3v10M13 3L5.5 8l7.5 5z" stroke="currentColor" strokeWidth="1.6" fill="currentColor" strokeLinejoin="round" />,
    next: <path d="M13 3v10M3 3l7.5 5L3 13z" stroke="currentColor" strokeWidth="1.6" fill="currentColor" strokeLinejoin="round" />,
    restart: <path d="M3.5 8a4.5 4.5 0 1 0 1.4-3.3M3.5 2.5v3h3" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />,
  }[name];
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
      {p}
    </svg>
  );
}

export function Header({
  runs,
  run,
  onPickRun,
}: {
  runs: RunIndexEntry[];
  run: Run | null;
  onPickRun: (name: string) => void;
}) {
  const pb = useUi((p) => `${p.playing}|${p.speed}|${run ? epochAt(run, p.t) : 0}|${p.holdingAt}|${p.holdOnReviews}`);
  const e = run ? epochAt(run, pb.t) : 0;
  const clock = useRef<HTMLDivElement>(null);
  useFrame((p, dirty) => {
    if (dirty && clock.current) clock.current.textContent = `t ${Math.round(p.t).toLocaleString("en-US")}`;
  });
  const kinds = run ? ([...new Set(run.agents.map((a) => a.kind))] as ModelKind[]) : [];
  const nLLM = run ? run.decisions.length : 0;

  return (
    <header className="topbar">
      <a className="brand" href="./" title="Start here">
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
          <rect width="32" height="32" rx="8" fill="#151a26" />
          <path d="M6 21 L12 14 L17 18 L26 8" stroke="#7b8cff" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="26" cy="8" r="2.6" fill="#2dd4bf" />
        </svg>
        <div>
          <div className="brand-name">MARKET ARENA</div>
          <div className="brand-sub">AI traders on a simulated exchange</div>
        </div>
      </a>

      <label className="run-picker">
        <span>run</span>
        <select value={run?.name ?? ""} onChange={(ev) => onPickRun(ev.target.value)}>
          {runs.map((r) => (
            <option key={r.name} value={r.name}>
              {r.name} · {r.epochs} epochs{r.decisions ? ` · ${r.decisions} reviews` : ""}
            </option>
          ))}
        </select>
      </label>

      <div className="transport">
        <button className="icon-btn" title="Restart (Home)" onClick={() => pb.seek(0)}>
          <Icon name="restart" />
        </button>
        <button className="icon-btn" title="Previous epoch (←)" onClick={() => pb.stepEpoch(-1)}>
          <Icon name="prev" />
        </button>
        <button className="play-btn" title="Play / pause (Space)" onClick={() => pb.toggle()}>
          <Icon name={pb.playing ? "pause" : "play"} />
        </button>
        <button className="icon-btn" title="Next epoch (→)" onClick={() => pb.stepEpoch(1)}>
          <Icon name="next" />
        </button>
      </div>

      <div className="speeds" role="group" aria-label="speed">
        {SPEEDS.map((s) => (
          <button key={s} className={pb.speed === s ? "on" : ""} onClick={() => pb.setSpeed(s)}>
            {s}×
          </button>
        ))}
      </div>

      <div className="clock">
        <div className="clock-epoch">
          EPOCH <b>{e}</b>
          <span>/{run ? run.epochs.length - 1 : 0}</span>
        </div>
        <div className="clock-t mono" ref={clock} />
      </div>

      <button
        className={`toggle ${pb.holdOnReviews ? "on" : ""}`}
        title="Pause the clock while agents review, so rationales can be read"
        onClick={() => {
          pb.holdOnReviews = !pb.holdOnReviews;
          if (!pb.holdOnReviews) pb.skipHold();
          pb.invalidate();
        }}
      >
        hold at reviews
      </button>
      {pb.holdingAt !== null && (
        <span className="reviewing" onClick={() => pb.skipHold()} title="Click to skip">
          <i /> agents reviewing
        </span>
      )}

      <span className="spacer" />

      <div className="models">
        {kinds.map((k) => (
          <ModelBadge key={k} kind={k} />
        ))}
      </div>
      <div className="cost" title={`${nLLM} LLM reviews in this run`}>
        <label>LLM cost</label>
        <span className="mono">{fmtUsd(run?.llmCost)}</span>
      </div>
    </header>
  );
}
