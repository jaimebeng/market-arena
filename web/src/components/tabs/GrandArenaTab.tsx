import { useEffect, useMemo, useRef, useState } from "react";

/** The Grand Arena: every experiment in one market, with a different story every run. Plays a
 * run's live stream (live.jsonl): from the server while the run happens, or a recorded run. */

type Line = { k: string; [key: string]: any };
type RunEntry = { id: string; seed: number; label?: string; epochs?: number; cost?: number; running?: boolean; found?: string[] };

const BASE = import.meta.env.BASE_URL;
const API =
  new URLSearchParams(window.location.search).get("api") ||
  (import.meta.env.VITE_LAB_API as string | undefined) ||
  "http://localhost:8000";

const ROLE_COLOR: Record<string, string> = {
  maker: "#7b8cff",
  taker: "#2dd4bf",
  investor: "#f5b74f",
  regulator: "#f472b6",
  red_team: "#ef4444",
  central_bank: "#a78bfa",
  finfluencer: "#fb923c",
};
const ROLE_LABEL: Record<string, string> = {
  maker: "market maker",
  taker: "quant",
  investor: "investor",
  regulator: "regulator",
  red_team: "red team",
  central_bank: "central bank",
  finfluencer: "finfluencer",
};
const SPEEDS = [1, 2, 4, 8, 16];
const COST = (l: Line) => (l.k === "f" ? 1 : l.k === "decision" ? 5 : l.k === "news" || l.k === "chat" ? 3 : 1);

function modelName(m?: string | null) {
  if (!m) return "scripted";
  if (!m.includes(":")) return m; // e.g. "GLFT closed form"
  const id = m.split(":")[1];
  if (m.startsWith("meta:")) return "Muse Spark " + (id.match(/\d\.\d/)?.[0] ?? "");
  if (m.startsWith("glimmer:")) return "Glimmer 30B";
  return "Spark Open";
}

export function GrandArenaTab() {
  const [online, setOnline] = useState(false);
  const [recorded, setRecorded] = useState<RunEntry[]>([]);
  const [liveRuns, setLiveRuns] = useState<RunEntry[]>([]);
  const [src, setSrc] = useState<{ kind: "recorded" | "live"; id: string } | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [running, setRunning] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [speed, setSpeed] = useState(4);
  const [playing, setPlaying] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [openQuant, setOpenQuant] = useState<Line | null>(null);
  const credit = useRef(0);

  // what is available: recorded runs (static files) and the live server, if it is running
  useEffect(() => {
    fetch(`${BASE}grand/index.json`)
      .then((r) => (r.ok ? r.json() : []))
      .then((x: RunEntry[]) => {
        setRecorded(x);
        if (x.length) setSrc((s) => s ?? { kind: "recorded", id: x[0].id });
      })
      .catch(() => setRecorded([]));
    fetch(`${API}/api/grand`)
      .then((r) => r.json())
      .then((x: RunEntry[]) => {
        setOnline(true);
        setLiveRuns(x);
      })
      .catch(() => setOnline(false));
  }, []);

  // load the chosen run; a live run is followed by polling for new lines
  useEffect(() => {
    if (!src) return;
    setLines([]);
    setCursor(0);
    credit.current = 0;
    setErr(null);
    let stop = false;
    if (src.kind === "recorded") {
      fetch(`${BASE}grand/${src.id}.json`)
        .then((r) => r.json())
        .then((x) => !stop && (setLines(x.lines), setRunning(false)))
        .catch((e) => setErr(String(e)));
      return () => void (stop = true);
    }
    let next = 0;
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/grand/${src.id}?since=${next}`).then((r) => r.json());
        if (stop) return;
        next = r.next;
        if (r.lines.length) setLines((l) => l.concat(r.lines));
        setRunning(r.running);
        if (r.error) setErr(r.error);
        if (r.running) setTimeout(poll, 1500);
      } catch (e) {
        if (!stop) setTimeout(poll, 3000);
      }
    };
    poll();
    return () => void (stop = true);
  }, [src]);

  // playback: frames advance at `speed` x 10 per second; decisions and headlines take a little longer
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setCursor((c) => {
        credit.current += speed;
        let i = c;
        while (i < lines.length && credit.current >= COST(lines[i])) {
          credit.current -= COST(lines[i]);
          i++;
        }
        if (i >= lines.length) credit.current = 0;
        return i;
      });
    }, 100);
    return () => clearInterval(id);
  }, [playing, speed, lines]);

  const start = async () => {
    setErr(null);
    try {
      const r = await fetch(`${API}/api/grand`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const x = await r.json();
      if (!r.ok) throw new Error(x.detail || r.statusText);
      setLiveRuns((l) => [{ id: x.id, seed: 0, running: true }, ...l]);
      setSrc({ kind: "live", id: x.id });
      setSpeed(16);
    } catch (e) {
      setErr(String(e));
    }
  };

  const view = useMemo(() => derive(lines.slice(0, cursor)), [lines, cursor]);
  const caughtUp = cursor >= lines.length;
  const S = view.start;

  return (
    <div className="grand">
      <div className="grand-intro">
        <div>
          <h3>The Grand Arena</h3>
          <p className="muted">
            Every experiment in one market. Two exchanges, three companies and an index fund: 7 order books in one
            economy. AI market makers, AI quants that write their own code, AI investors, a finfluencer, a red team, an
            AI regulator and an AI central bank trade alongside retail, institutions, an HFT, an options dealer and a
            leveraged crowd. Each run draws its own storyline from a fresh seed. Run it again and the news is different,
            the agents learn something different, and the quants find different strategies.
          </p>
        </div>
        <div className="grand-controls">
          <select
            value={src ? `${src.kind}:${src.id}` : ""}
            onChange={(e) => {
              const [kind, id] = e.target.value.split(/:(.*)/s);
              setSrc({ kind: kind as "live" | "recorded", id });
            }}
          >
            {!src && <option value="">pick a run</option>}
            {recorded.map((r) => (
              <option key={r.id} value={`recorded:${r.id}`}>
                {r.label ?? r.id} · seed {r.seed}
              </option>
            ))}
            {liveRuns.map((r) => (
              <option key={r.id} value={`live:${r.id}`}>
                {r.id} {r.running ? "· running" : ""} (this server)
              </option>
            ))}
          </select>
          <button onClick={() => setPlaying((p) => !p)}>{playing ? "❚❚ pause" : "▶ play"}</button>
          <button onClick={() => (setCursor(0), (credit.current = 0))}>⟲ restart</button>
          <span className="speeds">
            {SPEEDS.map((s) => (
              <button key={s} className={s === speed ? "on" : ""} onClick={() => setSpeed(s)}>
                {s}×
              </button>
            ))}
          </span>
          {online ? (
            <button className="primary" onClick={start} disabled={liveRuns.some((r) => r.running)}>
              ▶ Start a new run
            </button>
          ) : (
            <span className="muted small">Live runs need the local server (see the README); recorded runs play here.</span>
          )}
        </div>
      </div>
      {err && <div className="error-banner small">{err.slice(-600)}</div>}
      {!S ? (
        <div className="loading">{src ? "waiting for the market to open…" : "no runs yet"}</div>
      ) : (
        <>
          <StatusBar view={view} running={running} caughtUp={caughtUp} />
          <div className="grand-grid">
            <section className="panel grand-books">
              <div className="panel-title">
                Order books <span className="panel-sub">mid on each exchange · dashed: fair value · ▼ shocks</span>
              </div>
              <div className="books">
                {Object.keys(view.series.v).map((stock) => (
                  <BookChart key={stock} stock={stock} view={view} />
                ))}
              </div>
              <Venues view={view} />
            </section>
            <section className="panel grand-board">
              <div className="panel-title">
                Leaderboard <span className="panel-sub">equity, cents</span>
              </div>
              <Leaderboard view={view} />
            </section>
            <section className="panel grand-feed">
              <div className="panel-title">
                Live feed <span className="panel-sub">news, decisions, forum, notices</span>
              </div>
              <Feed view={view} onQuant={setOpenQuant} />
            </section>
          </div>
          <section className="panel grand-quants">
            <div className="panel-title">
              What the quants found <span className="panel-sub">strategy per review · ✓ passed the out-of-sample gate · click for the code</span>
            </div>
            <Genealogy view={view} onOpen={setOpenQuant} />
          </section>
          {view.end && <Storyline view={view} />}
        </>
      )}
      {openQuant && (
        <div className="grand-modal" onClick={() => setOpenQuant(null)}>
          <div className="panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel-title">
              {openQuant.agent} · epoch {openQuant.epoch} · {openQuant.name ?? "no submission"}{" "}
              <span className="panel-sub">{modelName(openQuant.model)}</span>
              <button className="toggle" onClick={() => setOpenQuant(null)}>
                close
              </button>
            </div>
            <p>{openQuant.hypothesis}</p>
            {openQuant.gate && (
              <p className="muted small">
                Gate: {openQuant.gate.passed ? "passed" : openQuant.gate.reason} · holdout P&L {openQuant.gate.holdout_pnl}
                {openQuant.resembles && ` · most like ${openQuant.resembles.signal} (ρ ${openQuant.resembles.corr})`}
              </p>
            )}
            {openQuant.code && <pre className="code">{openQuant.code}</pre>}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- derived state ---------------------------------------------------------------------------

type View = ReturnType<typeof derive>;

function derive(ls: Line[]) {
  const start = ls.find((l) => l.k === "start") ?? null;
  const series = { t: [] as number[], mid: {} as Record<string, number[]>, v: {} as Record<string, number[]> };
  let last: Line | null = null;
  let phase: Line | null = null;
  let end: Line | null = null;
  const feed: Line[] = [];
  const quants: Record<string, Line[]> = {};
  const shocks: Line[] = [];
  let lastEpoch: Line | null = null;
  let rate: number | null = null;
  let reported = 0;
  const roles: Record<string, string> = {}; // what each agent is, as its decisions say (red team, finfluencer)
  for (const l of ls) {
    if (l.k === "f") {
      series.t.push(l.t);
      for (const [a, x] of Object.entries(l.mid)) (series.mid[a] ??= []).push(x as number);
      for (const [a, x] of Object.entries(l.v)) (series.v[a] ??= []).push(x as number);
      last = l;
    } else if (l.k === "phase") {
      phase = l;
      reported = 0;
    } else if (l.k === "end") end = l;
    else if (l.k === "epoch") {
      lastEpoch = l;
      feed.push(l);
    } else {
      if (l.k === "decision") {
        reported++;
        roles[l.agent] = l.persona === "finfluencer" ? "finfluencer" : l.role;
        if (l.role === "taker") (quants[l.agent] ??= []).push(l);
        if (l.role === "central_bank" && typeof l.rate === "number") rate = l.rate;
        if (l.role === "maker" && !l.message && !l.rationale) continue;
      }
      if (l.k === "news" && l.kind === "shock") shocks.push(l);
      feed.push(l);
    }
  }
  return { start, series, last, phase, end, feed, quants, shocks, lastEpoch, rate, reported, roles };
}

// ---- panels ----------------------------------------------------------------------------------

function StatusBar({ view, running, caughtUp }: { view: View; running: boolean; caughtUp: boolean }) {
  const S = view.start!;
  const epoch = view.phase?.epoch ?? 0;
  const reviewing = view.phase?.phase === "review";
  return (
    <div className="grand-status">
      <span className="mono">seed {S.seed}</span>
      <span>
        quarter {Math.min(epoch + 1, S.epochs)} / {S.epochs}
      </span>
      {view.end ? (
        <span className="badge done">finished · ${view.end.cost?.toFixed(3)} of tokens</span>
      ) : reviewing ? (
        <span className="badge think">
          market paused: {view.reported} / {view.phase!.agents.length} AI agents have reported
          {running && caughtUp ? "…" : ""}
        </span>
      ) : (
        <span className="badge live">{running && caughtUp ? "● live" : "trading"}</span>
      )}
      {view.rate !== null && <span>policy rate {view.rate.toFixed(2)}%</span>}
      {view.lastEpoch?.macro && (
        <span>
          inflation {view.lastEpoch.macro.inflation?.toFixed(1)}% · output gap {view.lastEpoch.macro.output_gap?.toFixed(1)}%
        </span>
      )}
      <span className="muted small">{S.agents.length} participants</span>
    </div>
  );
}

function BookChart({ stock, view }: { stock: string; view: View }) {
  const S = view.start!;
  const total = S.epochs * S.steps_per_epoch;
  const venues: string[] = S.listings?.[stock] ?? [stock];
  const W = 300,
    H = 110;
  const { t } = view.series;
  const all = [...venues.flatMap((v) => view.series.mid[v] ?? []), ...(view.series.v[stock] ?? [])].filter((x) => x != null);
  if (!all.length) return null;
  let lo = Math.min(...all),
    hi = Math.max(...all);
  const pad = (hi - lo) * 0.08 + 1;
  lo -= pad;
  hi += pad;
  const x = (s: number) => (s / total) * W;
  const y = (p: number) => H - ((p - lo) / (hi - lo)) * H;
  const path = (xs: number[] = []) =>
    xs
      .map((p, i) => (p == null ? null : `${x(t[i]).toFixed(1)},${y(p).toFixed(1)}`))
      .filter(Boolean)
      .join(" ");
  const last = view.last;
  const gap =
    venues.length > 1 && last ? ((last.mid[venues[1]] / last.mid[venues[0]] - 1) * 1e4).toFixed(1) : null;
  const colors = ["var(--accent)", "var(--accent-2)"];
  return (
    <div className="book">
      <div className="book-head">
        <b>{stock}</b>
        {last && <span className="mono">{(last.mid[venues[0]] / 100).toFixed(2)}</span>}
        {venues.length > 1 && (
          <span className="muted small">
            {venues.map((v, i) => (
              <span key={v} style={{ color: colors[i] }}>
                {" "}
                {v}
              </span>
            ))}{" "}
            · gap {gap} bps
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="book-svg">
        {Array.from({ length: S.epochs - 1 }, (_, e) => (
          <line key={e} x1={x((e + 1) * S.steps_per_epoch)} x2={x((e + 1) * S.steps_per_epoch)} y1={0} y2={H} className="epoch-line" />
        ))}
        <polyline points={path(view.series.v[stock])} className="fv-line" />
        {venues.map((v, i) => (
          <polyline key={v} points={path(view.series.mid[v])} style={{ stroke: colors[i] }} className="mid-line" />
        ))}
        {view.shocks
          .filter((s) => s.asset === stock || s.asset === null)
          .map((s, i) => (
            <text key={i} x={x(s.t)} y={10} className={s.true_bps < 0 ? "shock down" : "shock up"} textAnchor="middle">
              ▼
            </text>
          ))}
      </svg>
    </div>
  );
}

function Venues({ view }: { view: View }) {
  const v = view.lastEpoch?.venues;
  if (!v) return null;
  return (
    <div className="venues">
      <div className="muted small">Share of volume, last quarter (home exchange vs entrant)</div>
      {Object.entries(v).map(([stock, s]: [string, any]) => {
        const [home, alt] = Object.keys(s.share);
        const h = s.share[home] * 100;
        return (
          <div key={stock} className="venue-row">
            <span className="mono">{stock}</span>
            <div className="venue-bar">
              <div style={{ width: `${h}%`, background: "var(--accent)" }}>{h.toFixed(0)}%</div>
              <div style={{ width: `${100 - h}%`, background: "var(--accent-2)" }}>{(100 - h).toFixed(0)}%</div>
            </div>
            <span className="muted small">
              {alt} · NBBO spread {s.nbbo_spread}¢
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Leaderboard({ view }: { view: View }) {
  const S = view.start!;
  const eq = view.last?.eq ?? {};
  const rows = S.agents
    .filter((a: any) => a.id in eq && a.role !== "regulator" && a.role !== "central_bank")
    .map((a: any) => ({ ...a, role: view.roles[a.id] ?? a.role, eq: eq[a.id] ?? 0 }))
    .sort((a: any, b: any) => b.eq - a.eq);
  const max = Math.max(1, ...rows.map((r: any) => Math.abs(r.eq)));
  return (
    <div className="board">
      {rows.map((r: any, i: number) => (
        <div key={r.id} className="board-row">
          <span className="rank">{i + 1}</span>
          <span className="who">
            <span className="dot" style={{ background: ROLE_COLOR[r.role] ?? "#888" }} />
            {r.id}
            <span className="muted small"> {ROLE_LABEL[r.role] ?? r.role} · {modelName(r.model)}</span>
          </span>
          <span className="bar-wrap">
            <span
              className={`bar ${r.eq < 0 ? "neg" : ""}`}
              style={{ width: `${(Math.abs(r.eq) / max) * 50}%`, [r.eq < 0 ? "right" : "left"]: "50%" } as any}
            />
          </span>
          <span className={`mono ${r.eq < 0 ? "neg" : "pos"}`}>{Math.round(r.eq).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

function decisionText(d: Line): string {
  switch (d.role) {
    case "taker":
      return d.name ? `${d.live ? "✓" : "✗"} ${d.name}: ${d.hypothesis ?? ""}` : "kept its current strategy";
    case "investor": {
      const t = Object.entries(d.targets ?? {})
        .filter(([, v]) => v)
        .map(([a, v]) => `${a} ${(v as number) > 0 ? "+" : ""}${v}`)
        .join(", ");
      return `${t ? `targets ${t}. ` : "flat. "}${d.rationale ?? ""}`;
    }
    case "central_bank":
      return `rate ${d.previous_rate?.toFixed?.(2)}% → ${d.rate?.toFixed?.(2)}%. ${d.statement ?? ""}`;
    case "regulator":
      return d.notice || d.rationale || `${(d.findings ?? []).length} findings`;
    case "red_team":
      return d.rationale ?? "set its spoofing tactics";
    default:
      return d.message ? `💬 ${d.message}` : d.rationale ?? "";
  }
}

function Feed({ view, onQuant }: { view: View; onQuant: (l: Line) => void }) {
  const items = view.feed.slice(-80).reverse();
  return (
    <div className="feed">
      {items.map((l, i) => {
        if (l.k === "news")
          return (
            <div key={i} className={`feed-item news ${l.kind === "shock" ? "shock" : ""}`}>
              <span className="tag">{l.kind === "macro" ? "MACRO" : l.kind === "shock" ? "BREAKING" : "NEWS"}</span> {l.headline}
            </div>
          );
        if (l.k === "forum")
          return (
            <div key={i} className="feed-item forum">
              <span className="tag">FORUM</span> <b>{l.agent}</b> {l.stance > 0.2 ? "🐂" : l.stance < -0.2 ? "🐻" : ""} {l.text}
            </div>
          );
        if (l.k === "chat")
          return (
            <div key={i} className={`feed-item chat ${l.kind}`}>
              <span className="tag">{l.kind === "notice" ? "REGULATOR" : "MAKER CHAT"}</span> <b>{l.agent}</b> {l.text}
            </div>
          );
        if (l.k === "epoch") {
          const liq = l.liquidations;
          return (
            <div key={i} className="feed-item epoch">
              — end of quarter {l.epoch + 1}
              {l.halts ? ` · ${l.halts} halts` : ""}
              {l.margin_calls ? ` · ${l.margin_calls} margin calls` : ""}
              {liq?.liquidations ? ` · ${liq.liquidations} liquidations` : ""} —
            </div>
          );
        }
        return (
          <div
            key={i}
            className={`feed-item decision ${l.role === "taker" ? "clickable" : ""}`}
            onClick={() => l.role === "taker" && onQuant(l)}
          >
            <span className="tag" style={{ color: ROLE_COLOR[l.role] }}>
              {String(ROLE_LABEL[l.role] ?? l.role ?? l.k).toUpperCase()}
            </span>{" "}
            <b>{l.agent}</b> {String(decisionText(l) ?? "").slice(0, 320)}
          </div>
        );
      })}
    </div>
  );
}

function Genealogy({ view, onOpen }: { view: View; onOpen: (l: Line) => void }) {
  const S = view.start!;
  const ids = S.agents.filter((a: any) => a.role === "taker").map((a: any) => a.id);
  return (
    <div className="genealogy">
      {ids.map((id: string) => {
        // the last submission of each review (a failed first attempt is followed by a second)
        const byEpoch: Record<number, Line> = {};
        for (const d of view.quants[id] ?? []) byEpoch[d.epoch] = d;
        const model = S.agents.find((a: any) => a.id === id)?.model;
        return (
          <div key={id} className="gen-row">
            <span className="who">
              {id} <span className="muted small">{modelName(model)}</span>
            </span>
            <div className="gen-cells">
              {Array.from({ length: S.epochs - 1 }, (_, e) => {
                const d = byEpoch[e];
                return (
                  <button
                    key={e}
                    className={`gen-cell ${d ? (d.live ? "ok" : "fail") : ""}`}
                    title={d?.hypothesis ?? ""}
                    onClick={() => d && onOpen(d)}
                  >
                    <span className="muted small">Q{e + 1}</span>
                    <span>{d ? `${d.live ? "✓" : "✗"} ${d.name ?? "kept"}` : ""}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Storyline({ view }: { view: View }) {
  const S = view.start!;
  return (
    <section className="panel grand-story">
      <div className="panel-title">
        This run's storyline <span className="panel-sub">drawn from seed {S.seed}; hidden from every agent until it happened</span>
      </div>
      <ul>
        {view.end!.storyline.map((s: any, i: number) => (
          <li key={i}>
            <span className="mono">quarter {Math.floor(s.at_step / S.steps_per_epoch) + 1}</span> ·{" "}
            {s.asset === "*" ? "all stocks" : s.asset} {s.bps ? `${s.bps > 0 ? "+" : ""}${s.bps} bps` : "(forced selling)"} · {s.headline}
          </li>
        ))}
      </ul>
    </section>
  );
}
