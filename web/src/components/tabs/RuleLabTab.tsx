import { useEffect, useRef, useState } from "react";

/** The Rule Lab: type or say a rule change; Muse Spark compiles it, the wind tunnel runs it against
 * today's rules on paired seeds, and Muse Spark writes the impact memo. Needs the lab server
 * (market_arena/server/lab.py); without it, recorded lab sessions are shown instead. */

type Row = {
  key: string;
  label: string;
  unit: string;
  investor_sign: number;
  today: number;
  proposal: number;
  change: number;
  se: number | null;
  up: number;
  n: number;
};
type Job = {
  id: string;
  proposal: string;
  ai_makers: boolean;
  status: "queued" | "done" | "error";
  stage: string;
  progress?: number;
  position?: number;
  compiled?: {
    kind: "compiled" | "declined";
    levers?: Record<string, unknown>;
    scenario?: string;
    restated?: string;
    hypothesis?: string;
    reason?: string;
  };
  table?: Row[];
  memo?: { verdict: string; summary: string; who_gains: string; who_pays: string; caveats: string };
  error?: string;
  cost_usd?: number;
  transcribed?: boolean;
};

const BASE = import.meta.env.BASE_URL;
const API =
  new URLSearchParams(window.location.search).get("api") ||
  (import.meta.env.VITE_LAB_API as string | undefined) ||
  "http://localhost:8000";

const EXAMPLES = [
  "Pay market makers a 2 basis point rebate and charge takers 3",
  "Add a 10 basis point financial transaction tax",
  "Ban short selling during a crash",
  "Route retail orders to a batch auction instead of the order book",
  "Make quotes rest for at least 20 seconds before they can be cancelled",
  "Halt trading for a minute if the price moves 1%",
];

export function RuleLabTab() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [text, setText] = useState(EXAMPLES[0]);
  const [aiMakers, setAiMakers] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [examples, setExamples] = useState<Job[]>([]);
  const [shown, setShown] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const rec = useRef<MediaRecorder | null>(null);
  const transcribed = useRef(false);

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((r) => setOnline(r.ok))
      .catch(() => setOnline(false));
    fetch(`${BASE}lab/examples.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setExamples)
      .catch(() => setExamples([]));
  }, []);

  // poll the running job
  useEffect(() => {
    if (!job || job.status !== "queued") return;
    const t = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/lab/${job.id}`);
        if (r.ok) setJob({ ...(await r.json()), transcribed: job.transcribed });
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job]);

  const submit = async () => {
    setErr(null);
    try {
      const r = await fetch(`${API}/api/lab`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal: text, ai_makers: aiMakers }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const { id } = await r.json();
      setJob({ id, proposal: text, ai_makers: aiMakers, status: "queued", stage: "queued", transcribed: transcribed.current });
    } catch (e) {
      setErr(String(e));
    }
  };

  const toggleMic = async () => {
    if (recording) {
      rec.current?.stop();
      return;
    }
    setErr(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        setTranscribing(true);
        try {
          const wav = await toWav(new Blob(chunks));
          const r = await fetch(`${API}/api/transcribe`, { method: "POST", body: wav, headers: { "Content-Type": "audio/wav" } });
          if (!r.ok) throw new Error(r.statusText);
          const { text: said } = await r.json();
          if (said) {
            setText(said);
            transcribed.current = true;
          } else setErr("Nothing was heard; try again closer to the microphone.");
        } catch (e) {
          setErr(`Transcription failed: ${e}`);
        } finally {
          setTranscribing(false);
        }
      };
      rec.current = mr;
      mr.start();
      setRecording(true);
    } catch (e) {
      setErr(`Microphone unavailable: ${e}`);
    }
  };

  const view = job ?? (online === false ? examples[shown] : null);
  return (
    <div className="lab">
      <div className="lab-intro">
        <h3>Rule Lab: test a market rule before it reaches a real market</h3>
        <p className="muted">
          Describe a rule change in plain English, or say it. <b>Muse Voice Transcribe</b> turns speech into text,{" "}
          <b>Muse Spark</b> compiles it into exchange levers (or declines), the wind tunnel runs it against today's rules on
          three paired seeds with AI market makers (<b>Muse Spark</b> and <b>Muse Spark Open</b>) who adapt to it, and Muse
          Spark writes the impact memo from the measured table.
        </p>
      </div>
      {online === false && (
        <div className="lab-offline">
          The live lab server isn't reachable from this page (<span className="mono">{API}</span>), so below are recorded lab
          sessions. Run it yourself: <span className="mono">uvicorn market_arena.server.lab:app --port 8000</span>, then open
          this page with <span className="mono">?tab=lab&amp;api=http://localhost:8000</span>.
        </div>
      )}
      {online && (
        <div className="lab-form">
          <div className="lab-input">
            <textarea
              value={text}
              rows={2}
              maxLength={600}
              onChange={(e) => {
                setText(e.target.value);
                transcribed.current = false;
              }}
            />
            <button className={`mic ${recording ? "on" : ""}`} onClick={toggleMic} disabled={transcribing} title="Say your proposal">
              {recording ? "■ stop" : transcribing ? "…" : "🎙 say it"}
            </button>
          </div>
          <div className="lab-examples">
            {EXAMPLES.map((x) => (
              <button key={x} className="chip" onClick={() => setText(x)}>
                {x}
              </button>
            ))}
          </div>
          <div className="lab-actions">
            <label className="small">
              <input type="checkbox" checked={aiMakers} onChange={(e) => setAiMakers(e.target.checked)} /> AI market makers
              (about 2 minutes; untick for scripted makers, about 30 s)
            </label>
            <button className="primary" onClick={submit} disabled={job?.status === "queued" || text.trim().length < 5}>
              Run the wind tunnel
            </button>
          </div>
        </div>
      )}
      {online === false && examples.length > 1 && (
        <div className="lab-examples">
          {examples.map((x, i) => (
            <button key={x.id} className={`chip ${i === shown ? "on" : ""}`} onClick={() => setShown(i)}>
              {x.proposal}
            </button>
          ))}
        </div>
      )}
      {err && <div className="error-banner">{err}</div>}
      {view && <JobView job={view} />}
    </div>
  );
}

function JobView({ job }: { job: Job }) {
  const c = job.compiled;
  return (
    <div className="lab-job">
      <div className="lab-steps">
        <Step done={!!c} active={job.stage === "compiling"} label="Muse Spark compiles the proposal" />
        <Step
          done={!!job.table}
          active={job.stage === "simulating"}
          label={`Wind tunnel: today vs proposal, 3 paired seeds${job.stage === "simulating" ? ` (${Math.round((job.progress ?? 0) * 100)}%)` : ""}`}
        />
        <Step done={!!job.memo} active={job.stage === "writing memo"} label="Muse Spark writes the impact memo" />
      </div>
      {job.status === "queued" && job.position ? <p className="muted small">Position in queue: {job.position}</p> : null}
      {job.error && <div className="error-banner">{job.error}</div>}
      {c && (
        <div className="lab-compiled">
          <div className="small muted">Proposal{job.transcribed ? " (spoken, transcribed by Muse Voice Transcribe)" : ""}</div>
          <div className="lab-proposal">“{job.proposal}”</div>
          {c.kind === "declined" ? (
            <p>
              <b>Declined:</b> {c.reason}
            </p>
          ) : (
            <>
              <div className="small muted">Compiled by Muse Spark</div>
              <p>{c.restated}</p>
              <div className="lab-levers">
                {Object.entries(c.levers ?? {}).map(([k, v]) => (
                  <span key={k} className="chip mono">
                    {k} = {String(v)}
                  </span>
                ))}
                <span className="chip">scenario: {c.scenario}</span>
                <span className="chip">makers: {job.ai_makers ? "AI (Spark, Spark Open) + GLFT" : "scripted"}</span>
              </div>
              {c.hypothesis && <p className="small muted">Hypothesis: {c.hypothesis}</p>}
            </>
          )}
        </div>
      )}
      {job.table && (
        <table className="lab-table">
          <thead>
            <tr>
              <th>Measure</th>
              <th>Today</th>
              <th>Proposal</th>
              <th>Change (± se)</th>
              <th>Seeds up</th>
            </tr>
          </thead>
          <tbody>
            {job.table.map((r) => {
              const sig = r.se != null && Math.abs(r.change) > 2 * r.se && r.change !== 0;
              const good = sig && r.investor_sign !== 0 && Math.sign(r.change) === r.investor_sign;
              const bad = sig && r.investor_sign !== 0 && Math.sign(r.change) === -r.investor_sign;
              return (
                <tr key={r.key}>
                  <td>
                    {r.label} {r.unit && <span className="muted small">{r.unit}</span>}
                  </td>
                  <td className="num">{fmt(r.today)}</td>
                  <td className="num">{fmt(r.proposal)}</td>
                  <td className={`num ${good ? "good" : bad ? "bad" : ""}`}>
                    {r.change > 0 ? "+" : ""}
                    {fmt(r.change)} {r.se != null && <span className="muted">± {fmt(r.se)}</span>}
                  </td>
                  <td className="num muted">
                    {r.up}/{r.n}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {job.memo && (
        <div className={`lab-memo verdict-${job.memo.verdict.replace(/ /g, "-")}`}>
          <div className="lab-verdict">{job.memo.verdict}</div>
          <p>{job.memo.summary}</p>
          <p>
            <b>Who gains:</b> {job.memo.who_gains}
          </p>
          <p>
            <b>Who pays:</b> {job.memo.who_pays}
          </p>
          <p className="muted small">
            <b>Caveats:</b> {job.memo.caveats}
          </p>
          {job.cost_usd != null && <p className="muted small">Model cost of this lab run: ${job.cost_usd.toFixed(3)}</p>}
        </div>
      )}
    </div>
  );
}

function Step({ done, active, label }: { done: boolean; active: boolean; label: string }) {
  return <div className={`lab-step ${done ? "done" : active ? "active" : ""}`}>{done ? "✓" : active ? "…" : "○"} {label}</div>;
}

function fmt(x: number): string {
  const a = Math.abs(x);
  return a >= 1000 ? x.toLocaleString(undefined, { maximumFractionDigits: 0 }) : a >= 10 ? x.toFixed(1) : x.toFixed(2);
}

/** Decode any recording the browser made and re-encode it as 16 kHz mono 16-bit WAV. */
async function toWav(blob: Blob): Promise<Blob> {
  const ctx = new AudioContext();
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  await ctx.close();
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + pcm.length * 2, true);
  str(8, "WAVEfmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, pcm.length * 2, true);
  pcm.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([buf], { type: "audio/wav" });
}
