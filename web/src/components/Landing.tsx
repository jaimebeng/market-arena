import { useEffect, useState } from "react";
import type { Experiment } from "../types";
import { fetchExperiment, fetchExperiments } from "../lib/load";
import { armsHeadline } from "../lib/arms";

interface Stat {
  value: string;
  label: string;
}

interface Story {
  id: string;
  kicker: string;
  title: string;
  body: string;
  href: string;
  cta: string;
  accent: string;
  stats: Stat[];
}

const STORIES: Story[] = [
  {
    id: "quants",
    kicker: "Strategy discovery",
    title: "AI quants write and test their own strategies",
    body: "Taker agents form a hypothesis, write Python, backtest it, and only trade if it survives a hidden out-of-sample gate.",
    href: "?run=final_multi&tab=gallery",
    cta: "Open the strategy gallery",
    accent: "#b18cff",
    stats: [
      { value: "+5,114", label: "Spark quant P&L, the only profitable taker" },
      { value: "6/12", label: "strategies passed the holdout gate" },
    ],
  },
  {
    id: "collusion",
    kicker: "Collusion lab",
    title: "Can AI market makers collude?",
    body: "Give the makers a chat room, then an antitrust warning, then an AI regulator watching the order flow, and measure what happens to spreads.",
    href: "?tab=wind&exp=collusion_lab",
    cta: "Open the collusion lab",
    accent: "#2dd4bf",
    stats: [
      { value: "Nearly all", label: "audits flagged the planted spoofer, with no false accusations" },
      { value: "No cartel", label: "formed when the makers were given a chat room" },
    ],
  },
  {
    id: "designer",
    kicker: "Market design",
    title: "An AI designs the exchange",
    body: "A Muse Spark designer proposes rule changes, tests them in the simulator and defends a recommendation on held-out seeds.",
    href: "?tab=designer&round=v1",
    cta: "Open the designer rounds",
    accent: "#f5b841",
    stats: [
      { value: "3 rounds", label: "round 1 gamed the metric; we tightened the mandate" },
      { value: "−14%", label: "volatility from round 3's speed bump, out of sample" },
    ],
  },
  {
    id: "arms",
    kicker: "Red team",
    title: "Can AI evade an AI regulator?",
    body: "A red-team trader must keep placing fake orders and chooses its tactics each epoch to dodge the Muse Spark surveillance officer.",
    href: "?tab=wind&exp=arms_race",
    cta: "Open the arms race",
    accent: "#f87171",
    stats: [
      { value: "Every audit", label: "scripted spoofer flagged for spoofing at warning or referral" },
      { value: "Rarely", label: "red teams flagged for spoofing once they chose their own tactics" },
    ],
  },
];

/** Arms-race headline from the export: spoofing warnings after epoch 0, scripted spoofer vs red teams. */
function armsStats(exp: Experiment): Stat[] | null {
  const h = armsHeadline(exp);
  if (!h || !h.scripted.auditsAfter0 || !h.red.auditsAfter0) return null;
  return [
    { value: `${h.scripted.spoofAfter0}/${h.scripted.auditsAfter0}`, label: "audits: scripted spoofer flagged for spoofing (warning or referral), after epoch 0" },
    { value: `${h.red.spoofAfter0}/${h.red.auditsAfter0}`, label: "audits: red teams flagged for spoofing once they chose their own tactics" },
  ];
}

/** Surveillance headline from the exported collusion lab, so it tracks re-exports. */
function regulatorStats(exp: Experiment): Stat | null {
  const v = exp.variants.find((x) => x.name === "chat_surveillance");
  if (!v) return null;
  let audits = 0;
  let flagged = 0;
  let falseAcc = 0;
  for (const s of v.seed_runs as Record<string, unknown>[]) {
    const reports = typeof s.reports === "number" ? s.reports : null;
    const rate = typeof s.spoofer_detection_rate === "number" ? s.spoofer_detection_rate : null;
    if (reports == null || rate == null) return null;
    audits += reports;
    flagged += Math.round(rate * reports);
    falseAcc += typeof s.false_accusations === "number" ? s.false_accusations : 0;
  }
  if (!audits) return null;
  return {
    value: `${flagged}/${audits}`,
    // spoofer_detection_rate counts warnings and referrals only (not "watch" findings)
    label: `audits: spoofer flagged at warning or referral · ${falseAcc} false accusation${falseAcc === 1 ? "" : "s"}`,
  };
}

function StoryCard({ s, i }: { s: Story; i: number }) {
  return (
    <a className="story-card" href={s.href} style={{ ["--accent-c" as string]: s.accent, animationDelay: `${i * 90}ms` }}>
      <div className="story-kicker">
        <span className="story-num mono">0{i + 1}</span>
        {s.kicker}
      </div>
      <h2>{s.title}</h2>
      <p>{s.body}</p>
      <div className="story-stats">
        {s.stats.map((st) => (
          <div key={st.label} className="story-stat">
            <span className="mono">{st.value}</span>
            <small>{st.label}</small>
          </div>
        ))}
      </div>
      <span className="story-cta">
        {s.cta} <span aria-hidden>→</span>
      </span>
    </a>
  );
}

export function Landing() {
  const [stories, setStories] = useState(STORIES);

  useEffect(() => {
    let alive = true;
    const patch = (id: string, stats: (cur: Stat[]) => Stat[] | null) => {
      if (alive) setStories((all) => all.map((s) => (s.id === id ? { ...s, stats: stats(s.stats) ?? s.stats } : s)));
    };
    fetchExperiments()
      .then((idx) => {
        const load = (name: string) => {
          const e = idx.find((x) => x.name === name);
          return e ? fetchExperiment(e) : Promise.reject(new Error(`${name} not exported`));
        };
        load("collusion_lab")
          .then((exp) =>
            patch("collusion", (cur) => {
              const st = regulatorStats(exp);
              return st ? [st, cur[1]] : null;
            }),
          )
          .catch(() => {});
        load("arms_race")
          .then((exp) => patch("arms", () => armsStats(exp)))
          .catch(() => {});
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="landing">
      <header className="landing-bar">
        <a className="brand" href="./">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
            <rect width="32" height="32" rx="8" fill="#151a26" />
            <path d="M6 21 L12 14 L17 18 L26 8" stroke="#7b8cff" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="26" cy="8" r="2.6" fill="#2dd4bf" />
          </svg>
          <div>
            <div className="brand-name">MARKET ARENA</div>
            <div className="brand-sub">AI traders on a simulated exchange</div>
          </div>
        </a>
        <span className="spacer" />
        <a className="landing-link" href="?explore=1">
          Replay explorer →
        </a>
      </header>

      <section className="hero">
        <div className="hero-kicker">Start here · about 2 minutes</div>
        <h1>
          A wind tunnel for markets<span className="hero-dim">:</span>
        </h1>
        <p className="hero-lede">
          AI traders built on Meta&rsquo;s <b className="spark">Muse Spark</b> models, graded against the maths of optimal market making.
        </p>
        <div className="hero-badges">
          <span className="badge badge-spark">Muse Spark</span>
          <span className="badge badge-spark_open">Muse Spark Open</span>
          <span className="badge badge-glft">GLFT benchmark</span>
        </div>
      </section>

      <section className="stories">
        {stories.map((s, i) => (
          <StoryCard key={s.id} s={s} i={i} />
        ))}
      </section>

      <a className="explorer-card" href="?explore=1">
        <div>
          <div className="story-kicker">The full replay</div>
          <h3>Watch the market play out</h3>
          <p>
            Order-book heatmap, every maker&rsquo;s quotes, live P&amp;L, and each agent&rsquo;s reasoning typed out as the replay reaches its
            review. Pick any run.
          </p>
        </div>
        <span className="story-cta">
          Open the replay explorer <span aria-hidden>→</span>
        </span>
      </a>
    </div>
  );
}
