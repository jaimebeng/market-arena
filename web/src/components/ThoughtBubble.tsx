import { useRef } from "react";
import type { AgentView, Decision, Run } from "../types";
import { TYPE_CHARS_PER_SEC, useFrame, useUi } from "../lib/playback";
import { latestDecision } from "../lib/query";
import { fmtCompact } from "../lib/format";

export function decisionText(d: Decision): string {
  return d.role === "taker" ? d.hypothesis ?? "" : d.rationale ?? "";
}

function staticText(agent: AgentView, run: Run): string {
  if (agent.kind === "glft")
    return "Closed-form optimal quotes (Guéant–Lehalle–Fernandez-Tapia) from the calibrated fill curve. The benchmark every LLM maker is measured against.";
  if (!agent.isLLM) return "Fixed scripted policy. No LLM, no reviews.";
  const spe = run.config.steps_per_epoch;
  return agent.role === "taker"
    ? `Waiting for the first review: will study the book, write a strategy and face the holdout gate at t=${spe.toLocaleString("en-US")}.`
    : `Trading on its initial policy. First review at the end of epoch 0 (t=${spe.toLocaleString("en-US")}).`;
}

/**
 * Latest rationale (maker) or hypothesis (taker), typed out when the replay reaches the review.
 * Typing is driven from the rAF loop and written straight to the DOM.
 */
export function ThoughtBubble({ run, agent }: { run: Run; agent: AgentView }) {
  const pb = useUi();
  const d = latestDecision(run, agent.id, pb.t);
  const textRef = useRef<HTMLSpanElement>(null);
  const toolsRef = useRef<HTMLDivElement>(null);
  const st = useRef({ key: "", start: 0, full: "", done: true });

  const key = d ? `${run.name}:${d.agent}:${d.t}` : `${run.name}:none:${agent.id}`;
  const full = d ? decisionText(d) : staticText(agent, run);

  useFrame((p) => {
    const el = textRef.current;
    if (!el) return;
    const s = st.current;
    const now = performance.now();
    if (s.key !== key) {
      s.key = key;
      s.full = full;
      // type only when we arrived here by playing; scrubbing shows the full text
      s.done = !(d && p.playing);
      s.start = now;
      el.textContent = s.done ? full : "";
      el.parentElement?.classList.toggle("typing", !s.done);
      if (toolsRef.current) toolsRef.current.dataset.revealed = s.done ? "all" : "0";
    }
    if (s.done) return;
    const n = Math.floor(((now - s.start) / 1000) * TYPE_CHARS_PER_SEC);
    const tools = toolsRef.current;
    if (tools) {
      const chips = tools.children;
      const per = 260; // ms per tool call "animation"
      for (let i = 0; i < chips.length; i++) chips[i].classList.toggle("shown", now - s.start > i * per);
    }
    if (n >= s.full.length) {
      el.textContent = s.full;
      s.done = true;
      el.parentElement?.classList.remove("typing");
      return;
    }
    el.textContent = s.full.slice(0, n);
  });

  const isLive = d && pb.holdingAt === d.t;
  const tok = d?.tokens ? (d.tokens.in ?? 0) + (d.tokens.out ?? 0) : 0;

  return (
    <div className={`bubble ${d ? "has-decision" : "idle"} ${isLive ? "live" : ""}`} key={key}>
      {d && (
        <div className="bubble-head">
          <span className="bubble-epoch">
            Epoch {d.epoch} review <span className="arrow">→</span> E{d.epoch + 1}
          </span>
          {d.role === "taker" && (
            <span className={`gate-chip ${d.gate?.passed ? "pass" : "fail"}`}>{d.gate?.passed ? "PASS" : "FAIL"}</span>
          )}
          <span className="bubble-meta">
            {d.seconds != null && `${d.seconds.toFixed(1)}s`}
            {tok > 0 && ` · ${fmtCompact(tok)} tok`}
          </span>
        </div>
      )}
      {d?.role === "taker" && <div className="bubble-strategy mono">{d.name}()</div>}
      <div className="bubble-text">
        <span ref={textRef} />
        <i className="caret" />
      </div>
      {d?.error && <div className="bubble-error">error: {d.error}</div>}
      {d && d.tools && d.tools.length > 0 && (
        <div className="tool-chips" ref={toolsRef}>
          {d.tools.map((t, i) => (
            <span key={i} className={`tool-chip ${t.startsWith("set_") || t.startsWith("submit_") ? "final" : ""}`}>
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
