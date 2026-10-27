import { useEffect, useState } from "react";
import type { DesignerIndexEntry, DesignerMetrics, DesignerRound, DesignerTrial } from "../../types";
import { fetchDesignerIndex, fetchDesignerRound } from "../../lib/load";
import { fmtNum, fmtSigned, fmtUsd } from "../../lib/format";
import { TranscriptShell, TurnList } from "../TranscriptDrawer";

const params = new URLSearchParams(window.location.search);
function setUrlParam(k: string, v: string) {
  const p = new URLSearchParams(window.location.search);
  p.set(k, v);
  window.history.replaceState(null, "", `${window.location.pathname}?${p}`);
}

type MetricKey = "taker_cost" | "spread" | "depth" | "volatility" | "mispricing_bps" | "collusion_index";
interface MetricMeta {
  key: MetricKey;
  label: string;
  unit: string;
  better: "lower" | "higher";
  digits: number;
  /** absolute change (collusion index is near zero, % is meaningless) */
  abs?: boolean;
}
const METRICS: Record<MetricKey, MetricMeta> = {
  taker_cost: { key: "taker_cost", label: "All-in taker cost", unit: "¢/lot", better: "lower", digits: 2 },
  spread: { key: "spread", label: "Quoted spread", unit: "¢", better: "lower", digits: 2 },
  depth: { key: "depth", label: "Top-5 depth", unit: "lots", better: "higher", digits: 1 },
  volatility: { key: "volatility", label: "Volatility", unit: "ticks/step", better: "lower", digits: 3 },
  mispricing_bps: { key: "mispricing_bps", label: "Mispricing", unit: "bps", better: "lower", digits: 1 },
  collusion_index: { key: "collusion_index", label: "Collusion index Δ", unit: "", better: "lower", digits: 2, abs: true },
};
const HEADLINE: MetricKey[] = ["taker_cost", "spread", "depth", "volatility", "collusion_index"];

/** The story so far, per round; rounds without an entry get a verdict computed from their data. */
const STORY: Record<string, { title: string; lesson: string }> = {
  v1: { title: "Optimised the wrong metric", lesson: "Goodhart / the maker-taker trap: quoted spreads narrowed, investors paid more." },
  v2: { title: "Overfit one seed", lesson: "Right metric, but a single-seed win that vanished out of sample." },
};

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const mval = (m: DesignerMetrics | null | undefined, k: string) => num(m?.[k]);
const mse = (m: DesignerMetrics | null | undefined, k: string) => num(m?.[`${k}_se`]);

// ---------------------------------------------------------------- rules ----

const LEVER_LABEL: Record<string, string> = {
  tick: "tick size",
  maker_fee_bps: "maker fee",
  taker_fee_bps: "taker fee",
  min_resting_steps: "speed bump",
  circuit_breaker_pct: "circuit breaker",
};

function leverValue(k: string, v: number | null | undefined): string {
  if (v == null) return k === "circuit_breaker_pct" ? "off" : "—";
  switch (k) {
    case "tick":
      return `${v}¢`;
    case "maker_fee_bps":
      return v < 0 ? `${fmtNum(-v, 1)} bps rebate` : `${fmtNum(v, 1)} bps`;
    case "taker_fee_bps":
      return `${fmtNum(v, 1)} bps`;
    case "min_resting_steps":
      return v ? `${v} steps` : "off";
    case "circuit_breaker_pct":
      return `${fmtNum(v, v % 1 ? 1 : 0)}% move`;
    default:
      return String(v);
  }
}

function RuleChips({ rules }: { rules: Record<string, number | null> | undefined }) {
  const e = Object.entries(rules ?? {}).filter(([, v]) => v != null);
  if (!e.length) return <span className="rule-chip default">default rules</span>;
  return (
    <>
      {e.map(([k, v]) => (
        <span key={k} className={`rule-chip lever-${k}`}>
          {LEVER_LABEL[k] ?? k} {leverValue(k, v)}
        </span>
      ))}
    </>
  );
}

function rulesText(rules: Record<string, number | null> | undefined): string {
  const e = Object.entries(rules ?? {}).filter(([, v]) => v != null);
  return e.length ? e.map(([k, v]) => `${LEVER_LABEL[k] ?? k} ${leverValue(k, v)}`).join(" + ") : "keep the default rules";
}

// ---------------------------------------------------------------- changes ----

interface Change {
  v: number; // % change, or absolute for abs metrics
  se: number | null;
}

/** Change of `x` vs `b` (% or absolute), with a delta-method standard error from the two s.e.s. */
function change(meta: MetricMeta, b: DesignerMetrics | null | undefined, x: DesignerMetrics | null | undefined): Change | null {
  const bv = mval(b, meta.key);
  const xv = mval(x, meta.key);
  if (bv == null || xv == null) return null;
  const bs = mse(b, meta.key);
  const xs = mse(x, meta.key);
  if (meta.abs) return { v: xv - bv, se: bs != null || xs != null ? Math.hypot(bs ?? 0, xs ?? 0) : null };
  if (!bv) return null;
  const v = (xv / bv - 1) * 100;
  const se = bs != null || xs != null ? 100 * Math.hypot((xs ?? 0) / bv, ((bs ?? 0) * xv) / (bv * bv)) : null;
  return { v, se };
}

/** Out-of-sample change: ratio of means (as reported), s.e. from per-seed paired changes. */
function oosChange(meta: MetricMeta, r: DesignerRound): Change | null {
  const val = r.validation;
  if (!val?.default || !val.recommended) return null;
  const base = change(meta, val.default, val.recommended);
  const reported = meta.abs ? null : num(val.change_pct?.[meta.key]);
  const v = reported ?? base?.v;
  if (v == null) return null;
  const bySeed = new Map((val.default.seed_runs ?? []).map((s) => [s.seed, s]));
  const ds: number[] = [];
  for (const s of val.recommended.seed_runs ?? []) {
    const b = bySeed.get(s.seed);
    const bv = mval(b, meta.key);
    const xv = mval(s, meta.key);
    if (bv == null || xv == null || (!meta.abs && !bv)) continue;
    ds.push(meta.abs ? xv - bv : (xv / bv - 1) * 100);
  }
  let se: number | null = base?.se ?? null;
  if (ds.length > 1) {
    const m = ds.reduce((a, b) => a + b, 0) / ds.length;
    se = Math.sqrt(ds.reduce((a, d) => a + (d - m) ** 2, 0) / (ds.length - 1) / ds.length);
  }
  return { v, se };
}

function inSample(meta: MetricMeta, r: DesignerRound): Change | null {
  const t = r.rec_trial != null ? r.trials?.[r.rec_trial] : undefined;
  return t ? change(meta, r.trials?.[0]?.metrics, t.metrics) : null;
}

const fmtChange = (meta: MetricMeta, c: Change | null, withSe = true) =>
  c == null
    ? "—"
    : `${fmtSigned(c.v, meta.abs ? 2 : 1)}${meta.abs ? "" : "%"}${withSe && c.se != null && c.se > 0 ? ` ±${fmtNum(c.se, meta.abs ? 2 : 1)}` : ""}`;

const isGood = (meta: MetricMeta, v: number) => (meta.better === "lower" ? v < 0 : v > 0);

type Verdict = { cls: "held" | "reversed" | "vanished" | "flat" | "untested"; text: string };
function verdict(meta: MetricMeta, p: Change | null, o: Change | null): Verdict {
  if (!o) return { cls: "flat", text: "—" };
  const tol = meta.abs ? 0.1 : 3;
  const sig = Math.abs(o.v) > (o.se != null && o.se > 0 ? 2 * o.se : tol);
  if (!p) return { cls: "untested", text: sig ? (isGood(meta, o.v) ? "improved" : "worsened") : "no clear effect" };
  const promised = Math.abs(p.v) > tol;
  if (sig && promised && Math.sign(o.v) === Math.sign(p.v))
    return isGood(meta, o.v) ? { cls: "held", text: "held" } : { cls: "reversed", text: "worse, as tested" };
  if (sig && promised) return { cls: "reversed", text: "reversed" };
  if (sig && !promised) return { cls: isGood(meta, o.v) ? "held" : "reversed", text: isGood(meta, o.v) ? "bonus" : "side effect" };
  if (promised) return { cls: "vanished", text: "vanished" };
  return { cls: "flat", text: "flat, as promised" };
}

function metaFor(r: DesignerRound, k: MetricKey): MetricMeta {
  const m = METRICS[k];
  return k === "taker_cost" && r.taker_cost_derived ? { ...m, label: `${m.label} (derived)` } : m;
}

const DERIVED_NOTE = "derived for v1: spread/2 + taker fee (1 bp = 1¢ on a 10,000¢ asset); v1 was not scored on it";

// ---------------------------------------------------------------- story strip ----

function StoryCard({ r, entry, on, onClick }: { r?: DesignerRound; entry: DesignerIndexEntry; on: boolean; onClick: () => void }) {
  const story = STORY[entry.round];
  if (!r || r.pending) {
    return (
      <button className={`story-card pending ${on ? "on" : ""}`} onClick={onClick}>
        <div className="story-round mono">{entry.round}</div>
        <div className="story-title">{story?.title ?? "Replicated trials"}</div>
        <div className="story-line muted">
          <span className="live-dot" /> running · {r?.trials_done ?? entry.trials} trial{(r?.trials_done ?? entry.trials) === 1 ? "" : "s"} done
        </div>
        <div className="story-lesson muted">Every experiment on 3 seeds with standard errors; "keep the default rules" is an allowed answer.</div>
      </button>
    );
  }
  const tgt = metaFor(r, (r.target as MetricKey) ?? "spread");
  const p = inSample(tgt, r);
  const o = oosChange(tgt, r);
  const other = metaFor(r, tgt.key === "spread" ? "taker_cost" : "spread");
  const oo = oosChange(other, r);
  const keep = !Object.values(r.recommendation?.rules ?? {}).some((v) => v != null);
  const vd = verdict(tgt, p, o);
  const title =
    story?.title ??
    (keep ? "Kept the default rules" : vd.cls === "held" ? "Promise held out of sample" : vd.cls === "vanished" ? "Effect vanished out of sample" : "Mixed out of sample");
  return (
    <button className={`story-card ${on ? "on" : ""}`} onClick={onClick}>
      <div className="story-head">
        <span className="story-round mono">{entry.round}</span>
        <span className="muted small">mandate: {tgt.key === "spread" ? "quoted spread" : "all-in taker cost"}</span>
      </div>
      <div className="story-title">{title}</div>
      <div className="story-rec mono">{rulesText(r.recommendation?.rules)}</div>
      <div className="story-nums">
        <div>
          <label>promised</label>
          <span className={`mono ${p ? (isGood(tgt, p.v) ? "good" : "bad") : "muted"}`}>{p ? fmtChange(tgt, p, false) : "—"}</span>
          <small>{tgt.key === "spread" ? "spread" : "taker cost"}, in sample</small>
        </div>
        <div>
          <label>delivered</label>
          <span className={`mono ${o ? (Math.abs(o.v) < (o.se ? 2 * o.se : 3) ? "muted" : isGood(tgt, o.v) ? "good" : "bad") : "muted"}`}>
            {fmtChange(tgt, o, false)}
          </span>
          <small>out of sample</small>
        </div>
        {tgt.key === "spread" && oo && (
          <div>
            <label>all-in cost</label>
            <span className={`mono ${isGood(other, oo.v) ? "good" : "bad"}`}>{fmtChange(other, oo, false)}</span>
            <small>what investors paid</small>
          </div>
        )}
      </div>
      {story?.lesson && <div className="story-lesson muted">{story.lesson}</div>}
    </button>
  );
}

// ---------------------------------------------------------------- promise vs reality ----

function PromiseReality({ r }: { r: DesignerRound }) {
  const rows = HEADLINE.filter((k) => r.trials?.[0]?.metrics?.[k] != null || r.validation?.default?.[k] != null).map((k) => {
    const meta = metaFor(r, k);
    return { meta, p: inSample(meta, r), o: oosChange(meta, r) };
  });
  // order: target metric first
  rows.sort((a, b) => Number(b.meta.key === r.target) - Number(a.meta.key === r.target));
  const pctRows = rows.filter((x) => !x.meta.abs);
  const maxPct = Math.max(10, ...pctRows.flatMap((x) => [x.p, x.o].filter(Boolean).map((c) => Math.abs(c!.v) + (c!.se ?? 0))));
  const absRows = rows.filter((x) => x.meta.abs);
  const maxAbs = Math.max(0.5, ...absRows.flatMap((x) => [x.p, x.o].filter(Boolean).map((c) => Math.abs(c!.v) + (c!.se ?? 0))));
  const untested = r.rec_trial == null;

  const bar = (meta: MetricMeta, c: Change | null, kind: "promise" | "reality") => {
    const max = meta.abs ? maxAbs : maxPct;
    const pos = (x: number) => 50 + (Math.max(-max, Math.min(max, x)) / max) * 50;
    if (!c) return <div className="pr-track"><i className="pr-zero" /></div>;
    const l = Math.min(pos(0), pos(c.v));
    const w = Math.abs(pos(c.v) - pos(0));
    return (
      <div className="pr-track" title={`${kind === "promise" ? "in sample (what the designer saw)" : "out of sample (fresh seeds)"}: ${fmtChange(meta, c)}`}>
        <i className="pr-zero" />
        <i className={`pr-bar ${kind} ${isGood(meta, c.v) ? "good" : "bad"}`} style={{ left: `${l}%`, width: `${Math.max(0.6, w)}%` }} />
        {c.se != null && c.se > 0 && (
          <i className="pr-whisker" style={{ left: `${pos(c.v - c.se)}%`, width: `${pos(c.v + c.se) - pos(c.v - c.se)}%` }} />
        )}
      </div>
    );
  };

  return (
    <div className="comp-card pr-card">
      <div className="card-title">
        Promise vs reality <span className="muted">· change vs default rules: in sample (what the designer saw) → out of sample (seeds {r.validation?.seeds.join(", ")})</span>
      </div>
      <div className="pr-legend">
        <span>
          <i className="pr-sw promise" /> promised (in sample{(r.trial_seeds?.length ?? 1) > 1 ? `, ${r.trial_seeds!.length} seeds` : ", 1 seed"})
        </span>
        <span>
          <i className="pr-sw reality" /> delivered (out of sample, ± s.e. over paired seeds)
        </span>
        <span className="muted">green = better for investors / markets</span>
      </div>
      {untested && (
        <div className="wt-warn">The recommended rulebook was never tested as a whole in sample. Designer's expectation: {r.recommendation?.expected_effects}</div>
      )}
      <div className="pr-rows">
        {rows.map(({ meta, p, o }) => {
          const vd = verdict(meta, p, o);
          return (
            <div key={meta.key} className={`pr-row ${meta.key === r.target ? "target" : ""}`}>
              <div className="pr-label">
                <span title={meta.key === "taker_cost" && r.taker_cost_derived ? DERIVED_NOTE : undefined}>{meta.label}</span>
                {meta.key === r.target && <span className="target-tag">mandate</span>}
                <span className="muted small">{meta.abs ? "Δ points" : "%"}</span>
              </div>
              <div className="pr-bars">
                {bar(meta, p, "promise")}
                {bar(meta, o, "reality")}
              </div>
              <div className="pr-nums mono">
                <span className={p ? (isGood(meta, p.v) ? "good" : "bad") : "muted"}>{fmtChange(meta, p)}</span>
                <span className={o ? (isGood(meta, o.v) ? "good" : "bad") : "muted"}>{fmtChange(meta, o)}</span>
              </div>
              <span className={`pr-verdict ${vd.cls}`}>{vd.text}</span>
            </div>
          );
        })}
      </div>
      <div className="wt-caption">
        Promised = the recommended rulebook's own trial vs the default-rules trial. Delivered = default vs recommended re-run on fresh seeds; the headline % is the
        change in means (as in RESULTS.md), the ± is the standard error of the per-seed paired change. Collusion index in absolute Δ points.
        {r.taker_cost_derived && ` Taker cost ${DERIVED_NOTE}.`}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- target chart ----

function TrialChart({ r }: { r: DesignerRound }) {
  const meta = metaFor(r, (r.target as MetricKey) ?? "spread");
  const trials = (r.trials ?? []).filter((t) => t.metrics);
  const base = mval(trials[0]?.metrics, meta.key);
  const vals = trials.flatMap((t) => {
    const v = mval(t.metrics, meta.key);
    const s = mse(t.metrics, meta.key) ?? 0;
    return v == null ? [] : [v - s, v + s];
  });
  if (base == null || !vals.length) return <div className="muted small">No {meta.label.toLowerCase()} in these trials.</div>;
  const lo = Math.min(base, ...vals);
  const hi = Math.max(base, ...vals);
  const pad = (hi - lo) * 0.08 || 1;
  const x = (v: number) => ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100;
  return (
    <div className="tc">
      {trials.map((t) => {
        const v = mval(t.metrics, meta.key)!;
        const s = mse(t.metrics, meta.key);
        const c = change(meta, trials[0].metrics, t.metrics);
        const good = c ? isGood(meta, c.v) : false;
        const isBase = t.i === 0;
        const rec = t.i === r.rec_trial;
        return (
          <div key={t.i} className={`tc-row ${rec ? "rec" : ""} ${isBase ? "base" : ""}`} title={`${t.label}: ${rulesText(t.rules)}\n${t.hypothesis}`}>
            <span className="tc-label">
              <span className="mono muted">#{t.i}</span> {t.label}
              {rec && <span className="rec-tag">recommended</span>}
            </span>
            <div className="tc-track">
              <i className="tc-base" style={{ left: `${x(base)}%` }} />
              {!isBase && (
                <i className={`tc-bar ${good ? "good" : "bad"}`} style={{ left: `${Math.min(x(base), x(v))}%`, width: `${Math.abs(x(v) - x(base))}%` }} />
              )}
              {s != null && s > 0 && <i className="tc-whisker" style={{ left: `${x(v - s)}%`, width: `${x(v + s) - x(v - s)}%` }} />}
              <i className={`tc-dot ${isBase ? "base" : good ? "good" : "bad"}`} style={{ left: `${x(v)}%` }} />
            </div>
            <span className="tc-val mono">
              {fmtNum(v, meta.digits)}
              {s != null && s > 0 && <span className="muted"> ±{fmtNum(s, meta.digits)}</span>}
            </span>
            <span className={`tc-pct mono ${isBase ? "muted" : good ? "good" : "bad"}`}>{isBase ? "default" : fmtChange(meta, c, false)}</span>
          </div>
        );
      })}
      <div className="wt-caption">
        Dashed line: default rules{(r.trial_seeds?.length ?? 1) > 1 ? `; whiskers ± s.e. over ${r.trial_seeds!.length} seeds` : `; one seed per trial (${r.trial_seeds?.[0] ?? r.seed}), no error bars`}.
        {r.taker_cost_derived && meta.key === "taker_cost" && ` ${DERIVED_NOTE}.`}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- recommendation ----

function Recommendation({ r }: { r: DesignerRound }) {
  const rec = r.recommendation ?? {};
  const levers = Object.keys(r.rulebook ?? LEVER_LABEL);
  return (
    <div className="comp-card">
      <div className="card-title">
        Recommendation <span className="muted">· submitted rulebook vs default</span>
      </div>
      <table className="rules-diff">
        <thead>
          <tr>
            <th>lever</th>
            <th>default</th>
            <th>recommended</th>
          </tr>
        </thead>
        <tbody>
          {levers.map((k) => {
            const d = r.rulebook?.[k]?.default ?? null;
            const v = rec.rules && k in rec.rules ? rec.rules[k] : d;
            const changed = v !== d;
            return (
              <tr key={k} className={changed ? "changed" : ""} title={r.rulebook?.[k]?.meaning}>
                <td>{LEVER_LABEL[k] ?? k}</td>
                <td className="mono muted">{leverValue(k, d)}</td>
                <td className="mono">{changed ? <b>{leverValue(k, v)}</b> : <span className="muted">unchanged</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="block-label">rationale</div>
      <blockquote className="rationale">{rec.rationale ?? "—"}</blockquote>
      {rec.expected_effects && (
        <>
          <div className="block-label">expected effects (designer's words)</div>
          <div className="notes">{rec.expected_effects}</div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- lab notebook ----

function TrialCard({ r, t, best }: { r: DesignerRound; t: DesignerTrial; best: boolean }) {
  const tgt = metaFor(r, (r.target as MetricKey) ?? "spread");
  const base = r.trials?.[0]?.metrics;
  const c = change(tgt, base, t.metrics);
  const rec = t.i === r.rec_trial;
  const secondary = HEADLINE.filter((k) => k !== tgt.key && t.metrics?.[k] != null);
  return (
    <div className={`nb-trial ${rec ? "rec" : ""}`}>
      <div className="nb-trial-head">
        <span className="mono muted">#{t.i}</span>
        <b>{t.label}</b>
        {rec && <span className="rec-tag">recommended</span>}
        {best && !rec && <span className="best-tag">best in batch</span>}
      </div>
      <div className="nb-rules">
        <RuleChips rules={t.rules} />
      </div>
      {t.hypothesis && <div className="nb-hyp">{t.hypothesis}</div>}
      {t.metrics ? (
        <>
          <div className="nb-target">
            <span className="muted small">{tgt.label}</span>
            <span className="mono">
              {fmtNum(mval(t.metrics, tgt.key), tgt.digits)}
              {mse(t.metrics, tgt.key) != null && <span className="muted"> ±{fmtNum(mse(t.metrics, tgt.key), tgt.digits)}</span>}
            </span>
            {t.i > 0 && <span className={`mono ${c ? (isGood(tgt, c.v) ? "good" : "bad") : ""}`}>{fmtChange(tgt, c, false)}</span>}
          </div>
          <div className="nb-secondary mono">
            {secondary.map((k) => {
              const m = metaFor(r, k);
              const cc = change(m, base, t.metrics);
              return (
                <span key={k} title={m.label}>
                  {k === "collusion_index" ? "Δ" : k === "taker_cost" ? "cost" : k === "volatility" ? "vol" : k}{" "}
                  {fmtNum(mval(t.metrics, k), m.digits)}
                  {t.i > 0 && cc && <i className={isGood(m, cc.v) ? "good" : "bad"}> {fmtChange(m, cc, false)}</i>}
                </span>
              );
            })}
          </div>
        </>
      ) : (
        <div className="bubble-error">run failed</div>
      )}
    </div>
  );
}

function LabNotebook({ r }: { r: DesignerRound }) {
  const trials = r.trials ?? [];
  const tgt = metaFor(r, (r.target as MetricKey) ?? "spread");
  const batches = r.batches ?? [];
  const seen = new Set(batches.flatMap((b) => b.trials));
  const orphans = trials.filter((t) => t.i > 0 && !seen.has(t.i)).map((t) => t.i);
  const all = [
    { key: "base", title: "Reference", text: "Default rules, run for the designer before it starts.", trials: trials.length ? [0] : [], error: undefined as string | undefined },
    ...batches.map((b, k) => ({ key: `b${k}`, title: `Batch ${k + 1}`, text: b.text ?? "", trials: b.trials, error: b.error })),
    ...(orphans.length ? [{ key: "other", title: "Other trials", text: "", trials: orphans, error: undefined }] : []),
  ];
  return (
    <div className="comp-card">
      <div className="card-title">
        Lab notebook <span className="muted">· each run_experiments call is one batch: hypotheses, then results vs default</span>
      </div>
      <ol className="nb">
        {all.map((b) => {
          const ts = b.trials.map((i) => trials[i]).filter(Boolean);
          const bestI = ts
            .filter((t) => t.i > 0 && mval(t.metrics, tgt.key) != null)
            .sort((a, c) => (tgt.better === "lower" ? 1 : -1) * (mval(a.metrics, tgt.key)! - mval(c.metrics, tgt.key)!))[0]?.i;
          return (
            <li key={b.key} className="nb-batch">
              <div className="nb-batch-head">
                <span className="nb-dot" />
                <b>{b.title}</b>
                {b.text && <span className="nb-text">“{b.text}”</span>}
              </div>
              {b.error ? (
                <div className="nb-error muted small">rejected by the lab: {b.error}</div>
              ) : (
                <div className="nb-trials">
                  {ts.map((t) => (
                    <TrialCard key={t.i} r={r} t={t} best={t.i === bestI && ts.length > 1} />
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------- tab ----

export function DesignerTab() {
  const [index, setIndex] = useState<DesignerIndexEntry[] | null>(null);
  const [rounds, setRounds] = useState<Record<string, DesignerRound>>({});
  const [sel, setSel] = useState<string | null>(params.get("round"));
  const [drawer, setDrawer] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchDesignerIndex()
      .then(async (idx) => {
        setIndex(idx);
        const loaded = await Promise.all(idx.map((e) => fetchDesignerRound(e).catch(() => null)));
        const out: Record<string, DesignerRound> = {};
        loaded.forEach((r, i) => r && (out[idx[i].round] = r));
        setRounds(out);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="error-banner">{err}</div>;
  if (!index) return <div className="muted">loading designer rounds…</div>;
  if (!index.length)
    return (
      <div className="empty">
        <div className="empty-title">No market-designer rounds exported</div>
        <p>
          Run <code>python scripts/export_designer.py runs web/public/designer</code> after <code>python -m market_arena.runner.designer</code>.
        </p>
      </div>
    );

  const complete = index.filter((e) => rounds[e.round] && !rounds[e.round].pending);
  const cur = index.find((e) => e.round === sel) ?? complete[complete.length - 1] ?? index[0];
  const r = rounds[cur.round];
  const pick = (round: string) => {
    setSel(round);
    setUrlParam("round", round);
  };

  return (
    <div className="designer">
      <div className="story-strip">
        {index.map((e, k) => (
          <div key={e.round} className="story-cell">
            <StoryCard r={rounds[e.round]} entry={e} on={e.round === cur.round} onClick={() => pick(e.round)} />
            {k < index.length - 1 && <span className="story-arrow">→</span>}
          </div>
        ))}
      </div>

      {!r ? (
        <div className="muted">loading {cur.round}…</div>
      ) : r.pending ? (
        <div className="empty">
          <div className="empty-title">Round {r.round} is still running</div>
          <p className="muted">
            {r.trials_done ?? 0} of {r.trial_folders ?? "?"} trial folders finished so far. Re-run <code>npm run export</code> when <code>runs/{r.name}/summary.json</code> appears.
          </p>
        </div>
      ) : (
        <>
          <div className="tab-toolbar designer-head">
            <div className="mandate">
              <div className="block-label">
                mandate · round {r.round} · judged on <b>{r.target === "taker_cost" ? "all-in taker cost" : "quoted spread"}</b>
              </div>
              <pre className="mandate-text">
                {r.mandate ?? "1. Low trading costs for investors: a tight average bid-ask spread (cents).\n2. Accurate, stable prices …\n3. Deep order books …\n4. A viable business …"}
              </pre>
            </div>
            <div className="designer-meta">
              <span className="chip mono">{r.model}</span>
              <span className="chip mono">budget {r.budget} experiments</span>
              <span className="chip mono">
                trial seed{(r.trial_seeds?.length ?? 1) > 1 ? "s" : ""} {r.trial_seeds?.join(", ")}
              </span>
              <span className="chip mono">validation seeds {r.validation?.seeds.join(", ")}</span>
              <span className="chip mono">designer {fmtUsd(r.designer_cost_usd)}</span>
              <button className="link-btn" onClick={() => setDrawer(true)}>
                designer transcript ›
              </button>
            </div>
          </div>
          {r.error && <div className="bubble-error">designer error: {r.error}</div>}

          <div className="designer-grid">
            <PromiseReality r={r} />
            <Recommendation r={r} />
            <div className="comp-card">
              <div className="card-title">
                {metaFor(r, (r.target as MetricKey) ?? "spread").label} per trial <span className="muted">· the mandate metric vs the default-rules line</span>
              </div>
              <TrialChart r={r} />
            </div>
            <LabNotebook r={r} />
          </div>

          {drawer && (
            <TranscriptShell
              title={
                <span className="agent-name">
                  <i className="agent-dot" style={{ background: "#7b8cff", boxShadow: "0 0 8px #7b8cff" }} />
                  AI market designer · {r.round}
                </span>
              }
              sub={`${r.model ?? ""} · ${r.transcript?.length ?? 0} turns · ${fmtUsd(r.designer_cost_usd)}`}
              onClose={() => setDrawer(false)}
            >
              {r.transcript?.length ? <TurnList turns={r.transcript} /> : <div className="empty small">No transcript recorded.</div>}
            </TranscriptShell>
          )}
        </>
      )}
    </div>
  );
}
