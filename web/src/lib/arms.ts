import type { Experiment, RedTeamTactics, SeedRun, Variant } from "../types";

/** Tactics the scripted spoofer uses, and that every red team starts epoch 0 with. */
export const DEFAULT_TACTICS: RedTeamTactics = { epoch: -1, spoof_size: 25, layers: 1, hold: 4, cycle: 30, bait_size: 2 };

export type Verdict = "spoof" | "wash" | "watch" | "clean" | "none";

const arr = (x: unknown): (number | null)[] | null => (Array.isArray(x) ? (x as (number | null)[]) : null);

/** Seed runs that carry a per-epoch verdict on the subject. */
export const hasVerdicts = (s: SeedRun) => arr(s.detection_by_epoch) != null;
export const variantHasVerdicts = (v: Variant) => v.seed_runs.some(hasVerdicts);
export const isArmsExperiment = (exp: Experiment) => exp.variants.some(variantHasVerdicts);
export const isRedTeam = (v: Variant) => v.seed_runs.some((s) => Array.isArray(s.red_team_tactics) && s.red_team_tactics.length > 0);

/** The regulator's verdict on the subject in epoch e's audit (worst finding wins). */
export function verdictAt(s: SeedRun, e: number): Verdict {
  const det = arr(s.detection_by_epoch);
  if (!det || e >= det.length || det[e] == null) return "none";
  if (det[e]) return "spoof";
  if (arr(s.wash_by_epoch)?.[e]) return "wash";
  if (arr(s.any_finding_by_epoch)?.[e]) return "watch";
  return "clean";
}

export interface VerdictStats {
  audits: number;
  spoof: number;
  wash: number;
  any: number;
  /** the same counts over audits after epoch 0 (epoch 0 always runs the default tactics) */
  auditsAfter0: number;
  spoofAfter0: number;
  washAfter0: number;
  anyAfter0: number;
  seedsWithWash: number;
}

export function verdictStats(runs: SeedRun[]): VerdictStats {
  const st: VerdictStats = { audits: 0, spoof: 0, wash: 0, any: 0, auditsAfter0: 0, spoofAfter0: 0, washAfter0: 0, anyAfter0: 0, seedsWithWash: 0 };
  for (const s of runs) {
    const det = arr(s.detection_by_epoch);
    if (!det) continue;
    let washed = false;
    det.forEach((d, e) => {
      if (d == null) return;
      const w = !!arr(s.wash_by_epoch)?.[e];
      const a = !!arr(s.any_finding_by_epoch)?.[e] || !!d || w;
      st.audits++;
      st.spoof += d ? 1 : 0;
      st.wash += w ? 1 : 0;
      st.any += a ? 1 : 0;
      washed ||= w;
      if (e > 0) {
        st.auditsAfter0++;
        st.spoofAfter0 += d ? 1 : 0;
        st.washAfter0 += w ? 1 : 0;
        st.anyAfter0 += a ? 1 : 0;
      }
    });
    if (washed) st.seedsWithWash++;
  }
  return st;
}

/** Tactics in force in each epoch 0..n-1: defaults in epoch 0, then the entry chosen after epoch e-1. */
export function tacticsByEpoch(s: SeedRun): { inForce: (RedTeamTactics | null)[]; fakeLots: (number | null)[]; n: number } {
  const tac = Array.isArray(s.red_team_tactics) ? s.red_team_tactics : [];
  const det = arr(s.detection_by_epoch) ?? [];
  const n = Math.max(det.length, ...tac.map((t) => t.epoch + 2), 1);
  const inForce: (RedTeamTactics | null)[] = Array.from({ length: n }, () => null);
  const fakeLots: (number | null)[] = Array.from({ length: n }, () => null);
  inForce[0] = DEFAULT_TACTICS;
  for (const t of tac) {
    if (t.epoch + 1 < n) inForce[t.epoch + 1] = t;
    if (t.epoch >= 0 && t.epoch < n) fakeLots[t.epoch] = t.fake_lots ?? null;
  }
  // an epoch without a new review keeps the previous tactics
  for (let e = 1; e < n; e++) if (!inForce[e]) inForce[e] = inForce[e - 1];
  return { inForce, fakeLots, n };
}

export const fakeSizePerLevel = (t: RedTeamTactics | null) =>
  t && t.spoof_size != null ? Math.floor(t.spoof_size / Math.max(1, t.layers ?? 1)) : null;

/** Headline for the landing page: scripted spoofer vs red teams, spoofing warnings after epoch 0. */
export function armsHeadline(exp: Experiment): { scripted: VerdictStats; red: VerdictStats } | null {
  const withV = exp.variants.filter(variantHasVerdicts);
  const scriptedV = withV.filter((v) => !isRedTeam(v));
  const redV = withV.filter(isRedTeam);
  if (!scriptedV.length || !redV.length) return null;
  return {
    scripted: verdictStats(scriptedV.flatMap((v) => v.seed_runs)),
    red: verdictStats(redV.flatMap((v) => v.seed_runs)),
  };
}
