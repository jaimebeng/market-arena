// Data model for Market Arena runs.
// Raw* types mirror the JSON produced by scripts/export_run.py (which mirrors runs/<id>/*.jsonl).
// The derived `Run` type is what the UI consumes (typed arrays, lookups).

export type Role = "maker" | "taker" | "scripted" | string;

export interface AgentInfo {
  id: string;
  role: Role;
  model: string | null;
}

export interface MakerPolicy {
  half_spread: number;
  skew: number;
  size?: number;
  max_inventory?: number;
  requote_every?: number;
  fair_value_adj?: string;
  [k: string]: unknown;
}

export interface MarketEpochMetrics {
  spread?: number;
  depth?: number;
  mispricing_bps?: number;
  vol_per_step?: number;
  volume?: number;
  [k: string]: number | undefined;
}

export interface AgentEpochMetrics {
  pnl?: number;
  equity?: number;
  fills?: number;
  volume?: number;
  maker_share?: number;
  fees?: number;
  inventory?: Record<string, number>;
  edge_per_lot?: number | null;
  markout_10?: number | null;
  markout_50?: number | null;
  markout_200?: number | null;
  quoted_half_spread?: Record<string, number | null>;
}

export interface Benchmarks {
  glft_hs?: number;
  nash_hs?: number;
  pareto_hs?: number;
}

export interface EpochMetrics {
  epoch: number;
  t0: number;
  t1: number;
  sim_seconds?: number;
  market: Record<string, MarketEpochMetrics>;
  agents: Record<string, AgentEpochMetrics>;
  policies?: Record<string, Record<string, MakerPolicy>>;
  // optional / upcoming
  benchmarks?: Record<string, Benchmarks>;
  collusion_index?: Record<string, number | null>;
  stylized?: Record<string, Record<string, number>>;
}

export interface ToolCall {
  name: string;
  args: unknown;
  ok: boolean;
  result: unknown;
}

export interface Turn {
  text: string | null;
  reasoning: string | null;
  calls: ToolCall[];
}

export interface GateStats {
  pnl?: number;
  sharpe?: number;
  ic?: number;
  turnover?: number;
}

export interface Gate {
  passed: boolean;
  reason?: string;
  insample?: GateStats;
  holdout?: GateStats;
}

interface DecisionBase {
  epoch: number;
  t: number;
  agent: string;
  model: string | null;
  notes?: string | null;
  tools?: string[];
  turns?: Turn[];
  tokens?: { in?: number; out?: number; reasoning?: number };
  cost?: number;
  seconds?: number;
  error?: string | null;
}

export interface MakerDecision extends DecisionBase {
  role: "maker";
  policy: Record<string, MakerPolicy>;
  rationale: string;
}

export interface TakerDecision extends DecisionBase {
  role: "taker";
  name: string;
  hypothesis: string;
  code: string;
  gate?: Gate;
  live?: boolean;
  similar_to?: Record<string, number>;
}

export type Decision = MakerDecision | TakerDecision;

export interface RawBook {
  L: number;
  base: number[];
  bp: number[];
  bq: number[];
  ap: number[];
  aq: number[];
}

export interface RawTradesAsset {
  t: number[];
  px: number[];
  q: number[];
  s: number[];
  mk: number[];
  tk: number[];
}

export interface RunConfig {
  seed?: number;
  steps_per_epoch: number;
  n_epochs: number;
  snapshot_every?: number;
  holdout?: number;
  glft_gamma?: number;
  rules?: { tick?: number; maker_fee_bps?: number; taker_fee_bps?: number; [k: string]: unknown };
  [k: string]: unknown;
}

export interface RawRun {
  format: 1;
  name: string;
  source: string;
  assets: string[];
  agents: AgentInfo[];
  config: RunConfig;
  llm_cost_usd: number | null;
  started: number | null;
  finished: number | null;
  complete: boolean;
  stylized?: RunStylized | null;
  snapshot_stride: number;
  t: number[];
  mid: Record<string, (number | null)[]>;
  v: Record<string, (number | null)[]>;
  book: Record<string, RawBook>;
  quotes: Record<string, Record<string, { b: (number | null)[]; a: (number | null)[] }>>;
  inv: Record<string, Record<string, (number | null)[]>>;
  equity: Record<string, (number | null)[]>;
  trades: { ids: string[]; n_total: number; sampled: boolean } & Record<string, unknown>;
  metrics: EpochMetrics[];
  decisions: Decision[];
}

/** meta.stylized: stylised facts of returns, per asset, for the traded mid and the hidden V. */
export interface StylizedFacts {
  horizon_steps?: number;
  excess_kurtosis?: number;
  hill_tail_index?: number;
  acf_returns?: number[];
  acf_abs_returns?: number[];
}
export type RunStylized = Record<string, { market?: StylizedFacts; fair_value?: StylizedFacts }>;

// ---------------------------------------------------------------- wind tunnel ----

export interface VariantBenchmarks extends Benchmarks {
  nash_skew?: number;
  pareto_skew?: number;
  adverse_selection?: number;
  n_makers?: number;
}

export interface VariantScalars {
  spread?: number | null;
  depth?: number | null;
  mispricing_bps?: number | null;
  volatility?: number | null;
  volume?: number | null;
  collusion_index?: number | null;
  llm_maker_half_spread?: number | null;
  maker_pnl_per_epoch?: number | null;
  llm_cost_usd?: number | null;
  epochs?: number | null;
}

export interface SeedRun extends VariantScalars {
  run?: string;
  collusion_by_epoch?: (number | null)[];
  llm_half_spread_by_epoch?: (number | null)[];
  complete?: boolean;
}

export interface Variant extends VariantScalars {
  name: string;
  label: string;
  change: string;
  n_seeds: number;
  provisional?: boolean;
  benchmarks?: Record<string, VariantBenchmarks>;
  seed_runs: SeedRun[];
  [k: `${string}_se`]: number | null | undefined;
}

export interface Experiment {
  format: 1;
  experiment: string;
  description: string;
  seeds: number[];
  provisional?: boolean;
  variants: Variant[];
}

export interface ExperimentIndexEntry {
  name: string;
  file: string;
  variants: string[];
  seeds: number[];
  provisional: boolean;
}

export interface RunIndexEntry {
  name: string;
  file: string;
  assets: string[];
  agents: AgentInfo[];
  epochs: number;
  steps: number;
  decisions: number;
  llm_cost_usd: number | null;
  finished: number | null;
  bytes: number;
}

// ---------------------------------------------------------------- derived ----

export type ModelKind = "spark" | "spark_open" | "glft" | "scripted" | "other";

export interface AgentView extends AgentInfo {
  index: number;
  kind: ModelKind;
  modelLabel: string;
  color: string;
  isLLM: boolean;
}

export interface AssetSeries {
  mid: Float64Array;
  v: Float64Array; // NaN when missing
  base: Float64Array;
  L: number;
  bp: Float32Array;
  bq: Float32Array;
  ap: Float32Array;
  aq: Float32Array;
  qRef: number; // ~95th percentile resting qty, for heatmap intensity
  lo: number; // min/max of mid & v over the run
  hi: number;
}

export interface TradeSeries {
  t: Float64Array;
  px: Float64Array;
  q: Float32Array;
  s: Int8Array;
  mk: Int16Array; // agent index or -1 for background
  tk: Int16Array;
}

export interface EpochSpan {
  epoch: number;
  t0: number;
  t1: number;
}

export interface Run {
  name: string;
  assets: string[];
  agents: AgentView[];
  agentById: Record<string, AgentView>;
  config: RunConfig;
  tick: number;
  llmCost: number;
  complete: boolean;
  stylized: RunStylized | null;
  n: number;
  t: Float64Array;
  tEnd: number;
  dtSnap: number;
  epochs: EpochSpan[];
  series: Record<string, AssetSeries>;
  quotes: Record<string, Record<string, { b: Float64Array; a: Float64Array }>>;
  inv: Record<string, Record<string, Float64Array>>;
  equity: Record<string, Float64Array>; // per agent, per snapshot (NaN when missing)
  trades: Record<string, TradeSeries>;
  tradesSampled: boolean;
  metrics: EpochMetrics[];
  decisions: Decision[]; // sorted by t
  decisionsByAgent: Record<string, Decision[]>;
  reviewTimes: number[]; // unique decision t, ascending
  makers: AgentView[];
  takers: AgentView[];
}
