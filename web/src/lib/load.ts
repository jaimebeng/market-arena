import type {
  AssetSeries,
  Decision,
  DesignerIndexEntry,
  DesignerRound,
  EpochSpan,
  Experiment,
  ExperimentIndexEntry,
  RawRun,
  RawTradesAsset,
  RegulatorDecision,
  Run,
  RunIndexEntry,
  TradeSeries,
} from "../types";
import { buildAgentViews } from "./agents";

const BASE = import.meta.env.BASE_URL;

export async function fetchIndex(): Promise<RunIndexEntry[]> {
  const r = await fetch(`${BASE}runs/index.json`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`runs/index.json: HTTP ${r.status}`);
  const j = await r.json();
  return j.runs as RunIndexEntry[];
}

export async function fetchRun(entry: RunIndexEntry): Promise<Run> {
  const r = await fetch(`${BASE}runs/${entry.file}`);
  if (!r.ok) throw new Error(`${entry.file}: HTTP ${r.status}`);
  return buildRun((await r.json()) as RawRun);
}

export async function fetchExperiments(): Promise<ExperimentIndexEntry[]> {
  const r = await fetch(`${BASE}experiments/index.json`, { cache: "no-cache" });
  if (!r.ok) return [];
  return ((await r.json()).experiments ?? []) as ExperimentIndexEntry[];
}

export async function fetchExperiment(entry: ExperimentIndexEntry): Promise<Experiment> {
  const r = await fetch(`${BASE}experiments/${entry.file}`);
  if (!r.ok) throw new Error(`${entry.file}: HTTP ${r.status}`);
  return (await r.json()) as Experiment;
}

export async function fetchDesignerIndex(): Promise<DesignerIndexEntry[]> {
  const r = await fetch(`${BASE}designer/index.json`, { cache: "no-cache" });
  if (!r.ok) return [];
  return ((await r.json()).rounds ?? []) as DesignerIndexEntry[];
}

export async function fetchDesignerRound(entry: DesignerIndexEntry): Promise<DesignerRound> {
  const r = await fetch(`${BASE}designer/${entry.file}`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${entry.file}: HTTP ${r.status}`);
  return (await r.json()) as DesignerRound;
}

const f64 =(a: (number | null)[] | undefined, n: number) => {
  const out = new Float64Array(n).fill(NaN);
  if (a) for (let i = 0; i < n && i < a.length; i++) out[i] = a[i] ?? NaN;
  return out;
};

export function buildRun(raw: RawRun): Run {
  const n = raw.t.length;
  const t = Float64Array.from(raw.t);
  const tEnd = n ? t[n - 1] : 0;
  const dtSnap = n > 1 ? t[1] - t[0] : raw.config.snapshot_every ?? 10;
  const agents = buildAgentViews(raw.agents);
  const agentById = Object.fromEntries(agents.map((a) => [a.id, a]));
  const tick = Number(raw.config.rules?.tick ?? 1) || 1;

  // epochs: from metrics, extended to cover the replay if the run is still in progress
  const spe = raw.config.steps_per_epoch || 2000;
  const epochs: EpochSpan[] = raw.metrics.map((m) => ({ epoch: m.epoch, t0: m.t0, t1: m.t1 }));
  let e = epochs.length;
  let last = epochs.length ? epochs[epochs.length - 1].t1 : 0;
  while (last < tEnd + 1) {
    epochs.push({ epoch: e++, t0: last, t1: last + spe });
    last += spe;
  }

  const series: Record<string, AssetSeries> = {};
  for (const a of raw.assets) {
    const b = raw.book[a];
    const mid = f64(raw.mid[a], n);
    const v = f64(raw.v[a], n);
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = 0; i < n; i++) {
      for (const x of [mid[i], v[i]]) {
        if (Number.isFinite(x)) {
          if (x < lo) lo = x;
          if (x > hi) hi = x;
        }
      }
    }
    const bq = Float32Array.from(b.bq);
    const aq = Float32Array.from(b.aq);
    // 95th percentile of non-zero resting qty
    const qs: number[] = [];
    const stride = Math.max(1, Math.floor(bq.length / 4000));
    for (let i = 0; i < bq.length; i += stride) {
      if (bq[i] > 0) qs.push(bq[i]);
      if (aq[i] > 0) qs.push(aq[i]);
    }
    qs.sort((x, y) => x - y);
    const qRef = qs.length ? Math.max(1, qs[Math.floor(qs.length * 0.95)]) : 1;
    series[a] = {
      mid,
      v,
      base: Float64Array.from(b.base),
      L: b.L,
      bp: Float32Array.from(b.bp),
      bq,
      ap: Float32Array.from(b.ap),
      aq,
      qRef,
      lo: Number.isFinite(lo) ? lo : 0,
      hi: Number.isFinite(hi) ? hi : 1,
    };
  }

  const quotes: Run["quotes"] = {};
  for (const [m, byAsset] of Object.entries(raw.quotes)) {
    quotes[m] = {};
    for (const [a, q] of Object.entries(byAsset)) quotes[m][a] = { b: f64(q.b, n), a: f64(q.a, n) };
  }
  const inv: Run["inv"] = {};
  for (const [id, byAsset] of Object.entries(raw.inv)) {
    inv[id] = {};
    for (const [a, q] of Object.entries(byAsset)) inv[id][a] = f64(q, n);
  }
  const equity: Run["equity"] = {};
  for (const [id, eq] of Object.entries(raw.equity)) equity[id] = f64(eq, n);

  // trades: map ids to agent index (-1 = background flow)
  const idMap = raw.trades.ids.map((id) => (agentById[id] ? agentById[id].index : -1));
  const trades: Record<string, TradeSeries> = {};
  for (const a of raw.assets) {
    const tr = raw.trades[a] as RawTradesAsset | undefined;
    const m = tr ? tr.t.length : 0;
    const ts: TradeSeries = {
      t: new Float64Array(m),
      px: new Float64Array(m),
      q: new Float32Array(m),
      s: new Int8Array(m),
      mk: new Int16Array(m),
      tk: new Int16Array(m),
    };
    for (let i = 0; i < m && tr; i++) {
      ts.t[i] = tr.t[i];
      ts.px[i] = tr.px[i];
      ts.q[i] = tr.q[i];
      ts.s[i] = tr.s[i];
      ts.mk[i] = idMap[tr.mk[i]] ?? -1;
      ts.tk[i] = idMap[tr.tk[i]] ?? -1;
    }
    trades[a] = ts;
  }

  const decisions = [...raw.decisions].sort((x, y) => x.t - y.t || x.agent.localeCompare(y.agent));
  const decisionsByAgent: Record<string, Decision[]> = {};
  for (const d of decisions) (decisionsByAgent[d.agent] ??= []).push(d);
  const reviewTimes = [...new Set(decisions.map((d) => d.t))].sort((x, y) => x - y);

  // agents seen only in decisions (no meta entry) still get a card
  for (const d of decisions) {
    if (!agentById[d.agent]) {
      const [v] = buildAgentViews([{ id: d.agent, role: d.role, model: d.model }]);
      v.index = agents.length;
      agents.push(v);
      agentById[v.id] = v;
    }
  }

  const chat = [...(raw.chat ?? [])].sort((x, y) => x.t - y.t || Number(x.kind === "notice") - Number(y.kind === "notice"));
  const reports = decisions.filter((d): d is RegulatorDecision => d.role === "regulator");
  const spoofers = raw.ground_truth?.spoofers?.length
    ? raw.ground_truth.spoofers
    : agents.filter((a) => /spoof/i.test(a.model ?? "")).map((a) => a.id);

  return {
    name: raw.name,
    assets: raw.assets,
    agents,
    agentById,
    config: raw.config,
    tick,
    llmCost: raw.llm_cost_usd ?? decisions.reduce((s, d) => s + (d.cost ?? 0), 0),
    complete: raw.complete,
    stylized: raw.stylized ?? null,
    n,
    t,
    tEnd,
    dtSnap,
    epochs,
    series,
    quotes,
    inv,
    equity,
    trades,
    tradesSampled: raw.trades.sampled,
    metrics: raw.metrics,
    decisions,
    decisionsByAgent,
    reviewTimes,
    makers: agents.filter((a) => a.role === "maker"),
    takers: agents.filter((a) => a.role === "taker"),
    traders: agents.filter((a) => a.role !== "regulator"),
    regulators: agents.filter((a) => a.role === "regulator"),
    reports,
    chat,
    spoofers,
    hasOrders: raw.metrics.some((m) => m.orders && Object.keys(m.orders).length > 0),
  };
}
