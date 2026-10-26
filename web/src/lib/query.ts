import type { Decision, MakerDecision, MakerPolicy, Run, TakerDecision } from "../types";
import { upperIndex } from "./format";

export function snapIndex(run: Run, t: number): number {
  return Math.max(0, upperIndex(run.t, t));
}

export function epochAt(run: Run, t: number): number {
  const ep = run.epochs;
  for (let i = ep.length - 1; i >= 0; i--) if (t >= ep[i].t0) return i;
  return 0;
}

/** Latest decision of an agent made at or before t. */
export function latestDecision(run: Run, agentId: string, t: number): Decision | undefined {
  const ds = run.decisionsByAgent[agentId];
  if (!ds) return undefined;
  let out: Decision | undefined;
  for (const d of ds) {
    if (d.t <= t) out = d;
    else break;
  }
  return out;
}

/** The maker policy in force at time t (metrics record the policy used during each epoch). */
export function policyAt(run: Run, agentId: string, t: number): Record<string, MakerPolicy> | undefined {
  const e = epochAt(run, t);
  const m = run.metrics[e]?.policies?.[agentId];
  if (m) return m;
  const d = latestDecision(run, agentId, t);
  if (d && d.role === "maker") return (d as MakerDecision).policy;
  for (let i = Math.min(e, run.metrics.length - 1); i >= 0; i--) {
    const p = run.metrics[i]?.policies?.[agentId];
    if (p) return p;
  }
  return undefined;
}

/** The taker strategy live at t: latest decision that passed the gate. */
export function liveStrategyAt(run: Run, agentId: string, t: number): TakerDecision | undefined {
  const ds = run.decisionsByAgent[agentId];
  let out: TakerDecision | undefined;
  for (const d of ds ?? []) {
    if (d.t > t) break;
    if (d.role === "taker" && (d.gate?.passed || d.live)) out = d as TakerDecision;
  }
  return out;
}

/** P&L at time t: snapshot equity when available, else cumulative equity of completed epochs. */
export function pnlAt(run: Run, agentId: string, t: number): number {
  const eq = run.equity[agentId];
  if (eq) {
    const v = eq[snapIndex(run, t)];
    if (Number.isFinite(v)) return v;
  }
  let out = 0;
  for (const m of run.metrics) {
    if (m.t1 > t + run.dtSnap) break;
    const a = m.agents[agentId];
    if (a?.equity != null) out = a.equity;
  }
  return out;
}

export function hasSnapshotEquity(run: Run, agentId: string): boolean {
  return !!run.equity[agentId];
}

/** Metrics of epochs fully completed by time t. */
export function completedMetrics(run: Run, t: number) {
  return run.metrics.filter((m) => m.t1 <= t + run.dtSnap);
}
