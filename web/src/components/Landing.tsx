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
    id: "grand",
    kicker: "Everything at once",
    title: "One market, 17 AI agents, a different story every run",
    body: "Two exchanges and 7 order books. AI makers, quants, investors, a finfluencer, a red team, a regulator and a central bank trade together while a random storyline unfolds: takeovers, tariffs, bank failures. Run it again and everything changes.",
    href: "?tab=grand",
    cta: "Watch the Grand Arena",
    accent: "#2dd4bf",
    stats: [
      { value: "−0.5 to 1.2", label: "the same AI makers' collusion index across six runs: competitive to cartel" },
      { value: "6 of 6", label: "runs where AI quants found index arbitrage on their own" },
    ],
  },
  {
    id: "lab",
    kicker: "Try it",
    title: "Test a market rule before it reaches a real market",
    body: "Type or say a rule change. Muse Voice Transcribe hears it, Muse Spark compiles it into exchange levers, AI market makers trade under it on paired markets, and Muse Spark writes the impact memo.",
    href: "?tab=lab",
    cta: "Open the Rule Lab",
    accent: "#7b8cff",
    stats: [
      { value: "+2.1 bps", label: "retail cost of a maker rebate, measured live; spreads looked 1.9¢ tighter" },
      { value: "~4 min", label: "per proposal, about a cent of tokens" },
    ],
  },
  {
    id: "crash",
    kicker: "Flash crash",
    title: "AI market makers cause a crash nobody programmed",
    body: "A fund is forced to sell. Made to keep quoting, AI makers pass the stock back and forth, each pricing off the last, while its true value never moves.",
    href: "?run=crash_no_kill_switch_s121&speed=25",
    cta: "Watch the crash replay",
    accent: "#f87171",
    stats: [
      { value: "21–78%", label: "falls in every market when makers could not step aside" },
      { value: "95/96", label: "decisions set a kill switch when they could; the fall was about 4%" },
    ],
  },
  {
    id: "herding",
    kicker: "Financial stability",
    title: "Do AI investors on the same model herd?",
    body: "The Bank of England's worry, tested: twelve AI investors trade through a forced sale, against twelve rule-following investors.",
    href: "?tab=wind&exp=herding",
    cta: "Open the herding experiment",
    accent: "#f5b841",
    stats: [
      { value: "91%", label: "of decisions on the same side for one model with one prompt (rule-followers: 61%)" },
      { value: "3×", label: "the volatility; four investing styles on the same model halved the herding" },
    ],
  },
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
  {
    id: "paper",
    kicker: "The Arena Times",
    title: "Every finding, on a front page",
    body: "Muse Spark writes each headline result from the measured numbers only, Muse Image draws the photograph, and the quote beside it is the agent's own logged words.",
    href: "?tab=paper",
    cta: "Read the front pages",
    accent: "#c9bfae",
    stats: [
      { value: "454/483", label: "recorded runs replay byte-identically with no model calls" },
      { value: "4 Meta models", label: "Muse Spark (text and vision), Spark Open, Voice Transcribe and Muse Image" },
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
