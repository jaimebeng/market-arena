import { useCallback, useEffect, useState } from "react";
import type { Run, RunIndexEntry } from "./types";
import { fetchIndex, fetchRun } from "./lib/load";
import { playback, SPEEDS } from "./lib/playback";
import { Header } from "./components/Header";
import { Timeline } from "./components/Timeline";
import { MarketPanel } from "./components/MarketPanel";
import { AgentCard } from "./components/AgentCard";
import { TranscriptDrawer } from "./components/TranscriptDrawer";
import { CompetitionTab } from "./components/tabs/CompetitionTab";
import { StrategyGallery } from "./components/tabs/StrategyGallery";
import { MarketQualityTab } from "./components/tabs/MarketQualityTab";

type Tab = "competition" | "gallery" | "quality";

const params = new URLSearchParams(window.location.search);

function setParam(k: string, v: string) {
  const p = new URLSearchParams(window.location.search);
  p.set(k, v);
  window.history.replaceState(null, "", `${window.location.pathname}?${p}`);
}

export default function App() {
  const [runs, setRuns] = useState<RunIndexEntry[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [asset, setAsset] = useState("A");
  const [drawer, setDrawer] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "competition");

  const loadRun = useCallback(async (entry: RunIndexEntry, autoplay = false) => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchRun(entry);
      playback.pause();
      playback.setRun(r);
      setRun(r);
      setAsset((a) => (r.assets.includes(a) ? a : r.assets[0]));
      setDrawer(null);
      setParam("run", r.name);
      if (autoplay) playback.play();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    playback.start();
    const sp = Number(params.get("speed"));
    if (SPEEDS.includes(sp)) playback.setSpeed(sp);
    if (params.get("fv") === "0") playback.showFairValue = false;
    fetchIndex()
      .then((idx) => {
        setRuns(idx);
        if (!idx.length) throw new Error("no runs exported — run scripts/export_run.py");
        const want = params.get("run");
        const entry = idx.find((r) => r.name === want) ?? idx[0];
        return loadRun(entry, params.get("autoplay") === "1");
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
    return () => playback.stop();
  }, [loadRun]);

  // keyboard shortcuts for recording the demo
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.code === "Space") {
        e.preventDefault();
        playback.toggle();
      } else if (e.key === "ArrowRight") playback.stepEpoch(1);
      else if (e.key === "ArrowLeft") playback.stepEpoch(-1);
      else if (e.key === "Home") playback.seek(0);
      else if (e.key === "v" || e.key === "V") {
        playback.showFairValue = !playback.showFairValue;
        playback.invalidate();
      } else if (e.key === "Enter" && playback.holdingAt !== null) playback.skipHold();
      else if (/^[1-6]$/.test(e.key) && !e.metaKey && !e.ctrlKey) playback.setSpeed(SPEEDS[Number(e.key) - 1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pickTab = (t: Tab) => {
    setTab(t);
    setParam("tab", t);
  };
  const drawerAgent = run && drawer ? run.agentById[drawer] : null;
  const nStrategies = run ? run.decisions.filter((d) => d.role === "taker").length : 0;

  return (
    <div className="app">
      <Header runs={runs} run={run} onPickRun={(name) => {
        const e = runs.find((r) => r.name === name);
        if (e) loadRun(e);
      }} />
      {run && <Timeline run={run} />}
      {error && <div className="error-banner">{error}</div>}
      {!run && loading && <div className="loading">loading run…</div>}
      {run && (
        <>
          <main className="main-grid">
            <MarketPanel run={run} asset={asset} onAsset={setAsset} />
            <section className="panel agents-col">
              <div className="panel-head">
                <div className="panel-title">
                  Agents <span className="panel-sub">{run.agents.length} traders · click for transcripts</span>
                </div>
              </div>
              <div className="agents-scroll">
                {run.agents.map((a) => (
                  <AgentCard key={a.id} run={run} agent={a} asset={asset} selected={drawer === a.id} onOpen={() => setDrawer(a.id)} />
                ))}
              </div>
            </section>
          </main>
          <section className="panel tabs-panel">
            <nav className="tabs">
              <button className={tab === "competition" ? "on" : ""} onClick={() => pickTab("competition")}>
                Competition
              </button>
              <button className={tab === "gallery" ? "on" : ""} onClick={() => pickTab("gallery")}>
                Strategy Gallery {nStrategies > 0 && <span className="count">{nStrategies}</span>}
              </button>
              <button className={tab === "quality" ? "on" : ""} onClick={() => pickTab("quality")}>
                Market quality
              </button>
              <span className="spacer" />
              <span className="muted small kbd-hint">
                <kbd>Space</kbd> play · <kbd>←</kbd>
                <kbd>→</kbd> epoch · <kbd>1</kbd>–<kbd>6</kbd> speed · <kbd>V</kbd> fair value
              </span>
            </nav>
            <div className="tab-body">
              {tab === "competition" && <CompetitionTab run={run} asset={asset} />}
              {tab === "gallery" && <StrategyGallery run={run} />}
              {tab === "quality" && <MarketQualityTab run={run} />}
            </div>
          </section>
          {drawerAgent && <TranscriptDrawer run={run} agent={drawerAgent} onClose={() => setDrawer(null)} />}
          {run.tradesSampled && <div className="foot-note muted small">background trades are sampled in this export</div>}
        </>
      )}
    </div>
  );
}
