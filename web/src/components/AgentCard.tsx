import { useMemo, useRef } from "react";
import type { AgentView, MakerPolicy, Run } from "../types";
import { BUY, SELL } from "../lib/agents";
import { fmtNum, fmtSigned } from "../lib/format";
import { useFrame, useUi } from "../lib/playback";
import { epochAt, latestDecision, liveStrategyAt, pnlAt, policyAt, snapIndex } from "../lib/query";
import { AgentName, ModelBadge, RoleTag } from "./ModelBadge";
import { Sparkline } from "./Sparkline";
import { ThoughtBubble } from "./ThoughtBubble";

function Delta({ cur, prev }: { cur?: number; prev?: number }) {
  if (cur == null || prev == null || Math.abs(cur - prev) < 1e-9) return null;
  const up = cur > prev;
  return <span className={`delta ${up ? "up" : "down"}`}>{up ? "▲" : "▼"}</span>;
}

function PolicyStats({ run, agent, asset }: { run: Run; agent: AgentView; asset: string }) {
  const pb = useUi((p) => epochAt(run, p.t));
  const e = epochAt(run, pb.t);
  const pol: MakerPolicy | undefined = policyAt(run, agent.id, pb.t)?.[asset];
  const prevT = e > 0 ? run.epochs[e - 1].t0 : -1;
  const prev: MakerPolicy | undefined = prevT >= 0 ? policyAt(run, agent.id, prevT)?.[asset] : undefined;
  if (!pol) return <div className="stat muted">no policy</div>;
  return (
    <>
      <div className="stat">
        <label>half-spread</label>
        <span className="mono">
          {fmtNum(pol.half_spread, 2)}
          <Delta cur={pol.half_spread} prev={prev?.half_spread} />
        </span>
      </div>
      <div className="stat">
        <label>skew</label>
        <span className="mono">
          {fmtNum(pol.skew, 2)}
          <Delta cur={pol.skew} prev={prev?.skew} />
        </span>
      </div>
      <div className="stat">
        <label>size · max</label>
        <span className="mono">
          {pol.size ?? "—"} · {pol.max_inventory ?? "—"}
        </span>
      </div>
    </>
  );
}

function TakerStats({ run, agent }: { run: Run; agent: AgentView }) {
  const pb = useUi((p) => latestDecision(run, agent.id, p.t)?.t ?? -1);
  const live = liveStrategyAt(run, agent.id, pb.t);
  const subs = (run.decisionsByAgent[agent.id] ?? []).filter((d) => d.t <= pb.t);
  const passed = subs.filter((d) => d.role === "taker" && d.gate?.passed).length;
  return (
    <>
      <div className="stat wide">
        <label>live strategy</label>
        <span className="mono">{live ? `${live.name}()` : "—"}</span>
      </div>
      <div className="stat">
        <label>holdout IC</label>
        <span className="mono">{fmtNum(live?.gate?.holdout?.ic, 3)}</span>
      </div>
      <div className="stat">
        <label>gate</label>
        <span className="mono">
          {passed}/{subs.length}
        </span>
      </div>
    </>
  );
}

/** Regulator card: case counts so far instead of P&L (it does not trade). */
function RegulatorStats({ run, agent }: { run: Run; agent: AgentView }) {
  const pb = useUi((p) => latestDecision(run, agent.id, p.t)?.t ?? -1);
  const filed = run.reports.filter((r) => r.agent === agent.id && r.t <= pb.t);
  const findings = filed.flatMap((r) => r.findings ?? []);
  const serious = findings.filter((f) => f.severity === "warning" || f.severity === "referral");
  const caught = run.spoofers.some((s) => serious.some((f) => f.agent === s && f.conduct === "spoofing"));
  const notices = run.chat.filter((c) => c.kind === "notice" && c.agent === agent.id && c.t <= pb.t).length;
  return (
    <>
      <div className="stat">
        <label>reports</label>
        <span className="mono">
          {filed.length}/{run.reports.filter((r) => r.agent === agent.id).length}
        </span>
      </div>
      <div className="stat">
        <label>findings</label>
        <span className="mono">
          {findings.length}
          {serious.length > 0 && <span className="muted"> · {serious.length} serious</span>}
        </span>
      </div>
      <div className="stat">
        <label>notices</label>
        <span className="mono">{notices}</span>
      </div>
      {run.spoofers.length > 0 && (
        <div className="stat wide">
          <label>planted spoofer</label>
          <span className={`mono ${caught ? "pass-c" : "muted"}`}>{caught ? "flagged ✓" : "not flagged yet"}</span>
        </div>
      )}
    </>
  );
}

/** Live P&L + inventory gauges, written to the DOM from the rAF loop. */
function LiveNumbers({ run, agent, maxInv }: { run: Run; agent: AgentView; maxInv: number }) {
  const pnl = useRef<HTMLSpanElement>(null);
  const bars = useRef<HTMLDivElement>(null);
  const invAssets = run.inv[agent.id] ? run.assets : [];
  useFrame((pb, dirty) => {
    if (!dirty) return;
    const v = pnlAt(run, agent.id, pb.t);
    if (pnl.current) {
      pnl.current.textContent = fmtSigned(v, 0);
      pnl.current.style.color = v > 0 ? BUY : v < 0 ? SELL : "";
    }
    const host = bars.current;
    if (!host) return;
    const i = snapIndex(run, pb.t);
    invAssets.forEach((a, k) => {
      const q = run.inv[agent.id][a][i];
      const row = host.children[k] as HTMLElement;
      const fill = row.querySelector(".inv-fill") as HTMLElement;
      const val = row.querySelector(".inv-val") as HTMLElement;
      const f = Number.isFinite(q) ? Math.max(-1, Math.min(1, q / maxInv)) : 0;
      fill.style.left = f >= 0 ? "50%" : `${50 + f * 50}%`;
      fill.style.width = `${Math.abs(f) * 50}%`;
      fill.style.background = f >= 0 ? BUY : SELL;
      val.textContent = Number.isFinite(q) ? fmtSigned(q, 0) || "0" : "—";
    });
  });
  return (
    <div className="card-live">
      <div className="pnl">
        <label>P&amp;L</label>
        <span className="mono pnl-val" ref={pnl}>
          0
        </span>
      </div>
      <div className="inv" ref={bars}>
        {invAssets.map((a) => (
          <div key={a} className="inv-row" title={`inventory ${a} (limit ±${maxInv})`}>
            <span className="inv-asset">{run.assets.length > 1 ? a : "inv"}</span>
            <div className="inv-track">
              <i className="inv-mid" />
              <i className="inv-fill" />
            </div>
            <span className="mono inv-val">0</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AgentCard({
  run,
  agent,
  asset,
  selected,
  onOpen,
}: {
  run: Run;
  agent: AgentView;
  asset: string;
  selected: boolean;
  onOpen: () => void;
}) {
  const maxInv = useMemo(() => {
    let m = 0;
    for (const met of run.metrics) {
      const p = met.policies?.[agent.id];
      if (p) for (const v of Object.values(p)) m = Math.max(m, v.max_inventory ?? 0);
    }
    if (m === 0 && run.inv[agent.id]) {
      for (const arr of Object.values(run.inv[agent.id])) for (const q of arr) if (Number.isFinite(q)) m = Math.max(m, Math.abs(q));
    }
    return Math.max(1, m || 20);
  }, [run, agent.id]);
  const nReviews = run.decisionsByAgent[agent.id]?.length ?? 0;

  return (
    <article
      className={`agent-card ${selected ? "selected" : ""}`}
      style={{ ["--agent" as string]: agent.color }}
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      title={nReviews ? "Open review transcripts" : undefined}
    >
      <header className="card-head">
        <AgentName agent={agent} />
        <RoleTag role={agent.role} />
        <span className="spacer" />
        <ModelBadge agent={agent} compact />
      </header>
      {agent.role !== "regulator" && (
        <div className="card-body">
          <LiveNumbers run={run} agent={agent} maxInv={maxInv} />
          <Sparkline run={run} agent={agent} />
        </div>
      )}
      <div className="card-stats">
        {agent.role === "regulator" ? (
          <RegulatorStats run={run} agent={agent} />
        ) : agent.role === "taker" ? (
          <TakerStats run={run} agent={agent} />
        ) : (
          <PolicyStats run={run} agent={agent} asset={asset} />
        )}
      </div>
      <ThoughtBubble run={run} agent={agent} />
      {nReviews > 0 && <div className="card-foot">{nReviews} {agent.role === "regulator" ? "reports" : "reviews"} · open transcript ›</div>}
    </article>
  );
}
