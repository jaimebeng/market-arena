import { useEffect, useState } from "react";

/** The AI agent driving test: one scorecard per Meta model, compiled from recorded runs by
 * scripts/driving_test.py, and "watch the tape": screen recordings Muse Wonder judged from video. */

type Cell = { value: string; verdict: "pass" | "warn" | "fail" | "info"; detail: string };
type Test = { area: string; id: string; section: string; name: string; how: string; cells: Record<string, Cell> };
type Model = { id: string; name: string; weights: string };
type Exam = { models: Model[]; tests: Test[] };

type Event = { kind?: string; stock?: string; start_s?: number; end_s?: number; evidence?: string };
type Answer = { events: Event[]; score: { correct: boolean; false_alarm: boolean } };
type TapeCase = { case: string; truth: { kind: string; stock: string | null; span: number[] | null }; [w: string]: unknown };
type Tape = { summary: Record<string, { correct: number; n: number; false_alarms: number }>; cases: TapeCase[] };

const BASE = import.meta.env.BASE_URL;
const MARK = { pass: "✓", warn: "!", fail: "✗", info: "·" };
const WATCHERS: [string, string][] = [
  ["wonder_video", "Muse Wonder · video"],
  ["wonder_stills", "Muse Wonder · 8 stills"],
  ["spark_stills", "Muse Spark 1.3 · 8 stills"],
];
const KIND: Record<string, string> = {
  none: "nothing (clean market)",
  spoofing: "spoofing",
  pump_and_dump: "pump-and-dump",
  fire_sale: "fire sale",
  liquidation_cascade: "liquidation cascade",
  flash_crash: "flash crash",
};

export function DrivingTestTab() {
  const [exam, setExam] = useState<Exam | null>(null);
  const [tape, setTape] = useState<Tape | null>(null);
  useEffect(() => {
    fetch(`${BASE}driving_test.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setExam)
      .catch(() => setExam(null));
    fetch(`${BASE}tape/results.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setTape)
      .catch(() => setTape(null));
  }, []);
  if (!exam) return <div className="loading">loading the driving test…</div>;
  let area = "";
  return (
    <div className="exam">
      <p className="exam-intro">
        Supervisors want algorithmic trading agents tested before they go live. This is that test for AI agents: each
        Meta model in the roles it has played here, scored from recorded runs that anyone can re-execute. A blank cell
        means the model was not tested in that role. <span className="muted">✓ pass · ! caution · ✗ fail</span>
      </p>
      <div className="exam-scroll">
        <table className="exam-table">
          <thead>
            <tr>
              <th />
              {exam.models.map((m) => (
                <th key={m.id}>
                  {m.name}
                  <div className="muted small">{m.weights === "open" ? "open weights" : "Meta Model API"}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {exam.tests.map((t) => {
              const head = t.area !== area;
              area = t.area;
              return [
                head && (
                  <tr key={`${t.id}-area`} className="exam-area">
                    <td colSpan={exam.models.length + 1}>{t.area}</td>
                  </tr>
                ),
                <tr key={t.id}>
                  <td className="exam-name">
                    {t.name}
                    <div className="muted small">
                      {t.how} <span className="mono">§{t.section}</span>
                    </div>
                  </td>
                  {exam.models.map((m) => {
                    const c = t.cells[m.id];
                    return (
                      <td key={m.id} className={`exam-cell ${c ? c.verdict : "na"}`} title={c?.detail}>
                        {c ? (
                          <>
                            <span className="exam-mark">{MARK[c.verdict]}</span> {c.value}
                          </>
                        ) : (
                          <span className="muted">·</span>
                        )}
                      </td>
                    );
                  })}
                </tr>,
              ];
            })}
          </tbody>
        </table>
      </div>
      {tape && <TapeSection tape={tape} />}
    </div>
  );
}

function TapeSection({ tape }: { tape: Tape }) {
  // open on the memecoin pump-and-dump: the clearest case to watch
  const [pick, setPick] = useState(() => Math.max(0, tape.cases.findIndex((x) => x.case.includes("crypto_mania"))));
  const c = tape.cases[pick];
  const t = c.truth;
  return (
    <section className="tape">
      <h3>Watch the tape</h3>
      <p className="muted">
        Each video is a recorded run's public market data, drawn as a 60-second screen recording: prices, order books,
        volume and a clock, with no account names. Muse Wonder watched the video; for comparison, Muse Wonder and Muse
        Spark 1.3 saw eight still frames.{" "}
        {WATCHERS.map(([w, label]) => (
          <span key={w} className="tape-score">
            {label}: <b>{tape.summary[w].correct}</b>/{tape.summary[w].n}
          </span>
        ))}
      </p>
      <div className="tape-picker">
        {tape.cases.map((x, i) => (
          <button key={x.case} className={i === pick ? "on" : ""} onClick={() => setPick(i)}>
            {i + 1}
          </button>
        ))}
      </div>
      <div className="tape-body">
        <video key={c.case} src={`${BASE}tape/${c.case}.mp4`} controls muted playsInline className="tape-video" />
        <div className="tape-answers">
          <div className="tape-truth">
            Planted: <b>{KIND[t.kind] ?? t.kind}</b>
            {t.stock && ` in ${t.stock}`}
            {t.span && t.kind !== "spoofing" && ` around t ${t.span[0]}–${t.span[1]} s`}
          </div>
          {WATCHERS.map(([w, label]) => {
            const a = c[w] as Answer | undefined;
            if (!a) return null;
            return (
              <div key={w} className={`tape-answer ${a.score.correct ? "ok" : "miss"}`}>
                <div className="tape-who">
                  {a.score.correct ? "✓" : "✗"} {label}
                </div>
                {a.events.length ? (
                  a.events.slice(0, 2).map((e, i) => (
                    <div key={i} className="small">
                      <b>{KIND[e.kind ?? ""] ?? e.kind}</b>
                      {e.stock && ` · ${e.stock}`}
                      {e.start_s != null && ` · t ${Math.round(e.start_s)}–${Math.round(e.end_s ?? e.start_s)} s`}
                      <div className="muted">{e.evidence}</div>
                    </div>
                  ))
                ) : (
                  <div className="small muted">reported nothing abnormal</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
