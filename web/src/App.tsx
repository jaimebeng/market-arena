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
import { WindTunnelTab } from "./components/tabs/WindTunnelTab";
import { SurveillanceCount, SurveillanceTab } from "./components/tabs/SurveillanceTab";
import { DesignerTab } from "./components/tabs/DesignerTab";
import { RuleLabTab } from "./components/tabs/RuleLabTab";
import { FrontPagesTab } from "./components/tabs/FrontPagesTab";
import { GrandArenaTab } from "./components/tabs/GrandArenaTab";
import { Landing } from "./components/Landing";

type Tab = "grand" | "competition" | "gallery" | "quality" | "surveillance" | "wind" | "designer" | "lab" | "paper";

const params = new URLSearchParams(window.location.search);
/** No query params at all: show the judge-friendly "Start here" landing. */
const LANDING = [...params.keys()].length === 0;
/** A deep link (?tab=...) puts the selected tab first, right under the header. */
const DEEP = params.has("tab");
/** Experiment-level tabs do not depend on the replayed run. */
const EXP_TABS = new Set<Tab>(["grand", "wind", "designer", "lab", "paper"]);

function setParam(k: string, v: string) {
  const p = new URLSearchParams(window.location.search);
  p.set(k, v);
  window.history.replaceState(null, "", `${window.location.pathname}?${p}`);
}

export default function App() {
  return LANDING ? <Landing /> : <Explorer />;
}

function Explorer() {
  const [runs, setRuns] = useState<RunIndexEntry[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [asset, setAsset] = useState("A");
  const [drawer, setDrawer] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "competition");
  const [replayOpen, setReplayOpen] = useState(false);

  const loadRun = useCallback(async (entry: RunIndexEntry, autoplay = false, initial = false) => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchRun(entry);
      playback.pause();
      playback.setRun(r);
      setRun(r);
      setAsset((a) => (r.assets.includes(a) ? a : r.assets[0]));
      setDrawer(null);
      // keep experiment deep links (?tab=wind&exp=...) clean: only record the run once it matters
      if (!initial || params.has("run") || !DEEP) setParam("run", r.name);
      if (autoplay) playback.play();
      // a deep link lands on finished results: start at the end so galleries and reports are complete
      else if (initial && DEEP) playback.seek(r.tEnd);
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
        return loadRun(entry, params.get("autoplay") === "1", true);
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
  const hasSurv = !!run && (run.regulators.length > 0 || run.chat.length > 0 || run.hasOrders);
  const shownTab: Tab = tab === "surveillance" && run && !hasSurv ? "competition" : tab;
  const expTab = EXP_TABS.has(shownTab);
  // deep links to experiment tabs hide the (unrelated) replay until asked for
  const showReplay = !DEEP || !expTab || replayOpen;

  const replay = run && showReplay && (
    <>
      <Timeline run={run} />
      <main className="main-grid">
            <MarketPanel run={run} asset={asset} onAsset={setAsset} />
            <section className="panel agents-col">
              <div className="panel-head">
                <div className="panel-title">
                  Agents{" "}
                  <span className="panel-sub">
                    {run.traders.length} traders{run.regulators.length ? ` · ${run.regulators.length} regulator` : ""} · click for transcripts
                  </span>
                </div>
              </div>
              <div className="agents-scroll">
                {run.agents.map((a) => (
                  <AgentCard key={a.id} run={run} agent={a} asset={asset} selected={drawer === a.id} onOpen={() => setDrawer(a.id)} />
                ))}
              </div>
            </section>
      </main>
    </>
  );

  const tabs = (
          <section className={`panel tabs-panel ${DEEP ? "deep" : ""}`}>
            <nav className="tabs">
              <button className={shownTab === "grand" ? "on" : ""} onClick={() => pickTab("grand")}>
                Grand Arena <span className="count new">live</span>
              </button>
              <button className={shownTab === "competition" ? "on" : ""} onClick={() => pickTab("competition")}>
                Competition
              </button>
              <button className={shownTab === "gallery" ? "on" : ""} onClick={() => pickTab("gallery")}>
                Strategy Gallery {nStrategies > 0 && <span className="count">{nStrategies}</span>}
              </button>
              <button className={shownTab === "quality" ? "on" : ""} onClick={() => pickTab("quality")}>
                Market quality
              </button>
              {run && hasSurv && (
                <button className={shownTab === "surveillance" ? "on" : ""} onClick={() => pickTab("surveillance")}>
                  Surveillance <SurveillanceCount run={run} />
                </button>
              )}
              <button className={shownTab === "wind" ? "on" : ""} onClick={() => pickTab("wind")}>
                Wind Tunnel <span className="count new">policy lab</span>
              </button>
              <button className={shownTab === "designer" ? "on" : ""} onClick={() => pickTab("designer")}>
                Designer <span className="count new">AI market design</span>
              </button>
              <button className={shownTab === "lab" ? "on" : ""} onClick={() => pickTab("lab")}>
                Rule Lab <span className="count new">try a rule</span>
              </button>
              <button className={shownTab === "paper" ? "on" : ""} onClick={() => pickTab("paper")}>
                Front pages
              </button>
              <span className="spacer" />
              {DEEP && expTab ? (
                <button className="toggle replay-toggle" onClick={() => setReplayOpen((o) => !o)}>
                  {replayOpen ? "hide market replay" : "show market replay ↓"}
                </button>
              ) : (
                <span className="muted small kbd-hint">
                  <kbd>Space</kbd> play · <kbd>←</kbd>
                  <kbd>→</kbd> epoch · <kbd>1</kbd>–<kbd>6</kbd> speed · <kbd>V</kbd> fair value
                </span>
              )}
            </nav>
            <div className="tab-body">
              {shownTab === "grand" && <GrandArenaTab />}
              {shownTab === "wind" && <WindTunnelTab />}
              {shownTab === "designer" && <DesignerTab />}
              {shownTab === "lab" && <RuleLabTab />}
              {shownTab === "paper" && <FrontPagesTab />}
              {!expTab && !run && <div className="loading">loading run…</div>}
              {run && shownTab === "competition" && <CompetitionTab run={run} asset={asset} />}
              {run && shownTab === "gallery" && <StrategyGallery run={run} />}
              {run && shownTab === "quality" && <MarketQualityTab run={run} asset={asset} />}
              {run && shownTab === "surveillance" && <SurveillanceTab run={run} onOpenAgent={setDrawer} />}
            </div>
          </section>
  );

  return (
    <div className="app">
      <Header
        runs={runs}
        run={run}
        onPickRun={(name) => {
          const e = runs.find((r) => r.name === name);
          if (e) loadRun(e);
        }}
      />
      {error && <div className="error-banner">{error}</div>}
      {DEEP ? (
        <>
          <div className="deep-bar">
            <a href="./">← Start here</a>
            {!expTab && run && (
              <span className="muted small">
                showing the end of <span className="mono">{run.name}</span> · press <kbd>Space</kbd> to replay it from the start
              </span>
            )}
          </div>
          {tabs}
          {replay && <div className="deep-replay">{replay}</div>}
        </>
      ) : (
        <>
          {replay}
          {!run && loading && <div className="loading">loading run…</div>}
          {run && tabs}
        </>
      )}
      {drawerAgent && run && <TranscriptDrawer run={run} agent={drawerAgent} onClose={() => setDrawer(null)} />}
      {run?.tradesSampled && showReplay && <div className="foot-note muted small">background trades are sampled in this export</div>}
    </div>
  );
}
