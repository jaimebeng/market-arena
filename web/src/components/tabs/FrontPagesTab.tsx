import { useEffect, useState } from "react";

/** "The Arena Times": each headline result written up by Muse Spark (from the measured facts only)
 * and illustrated by Muse Image. The quote beside each story is an agent's logged words, verbatim. */

type Page = {
  id: string;
  kicker: string;
  link: string;
  headline: string;
  subhead: string;
  lede: string;
  image: string;
  quote: { text: string; agent: string; model: string; epoch: number; source: string } | null;
};

const BASE = import.meta.env.BASE_URL;

export function FrontPagesTab() {
  const [pages, setPages] = useState<Page[]>([]);
  useEffect(() => {
    fetch(`${BASE}frontpages/index.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setPages)
      .catch(() => setPages([]));
  }, []);
  if (!pages.length) return <div className="loading">loading the paper…</div>;
  const [lead, ...rest] = pages;
  return (
    <div className="paper">
      <div className="masthead">
        <div className="masthead-title">The Arena Times</div>
        <div className="masthead-sub">
          All the news from the simulated markets · stories written by Muse Spark from measured results · photographs by Muse
          Image · quotes are the AI agents' own logged words
        </div>
      </div>
      <Story page={lead} lead />
      <div className="paper-grid">
        {rest.map((p) => (
          <Story key={p.id} page={p} />
        ))}
      </div>
    </div>
  );
}

function Story({ page, lead = false }: { page: Page; lead?: boolean }) {
  return (
    <article className={`story ${lead ? "lead" : ""}`}>
      <img src={`${BASE}${page.image}`} alt={page.headline} loading="lazy" />
      <div className="story-text">
        <div className="kicker">{page.kicker}</div>
        <h2>{page.headline}</h2>
        <div className="subhead">{page.subhead}</div>
        <p>{page.lede}</p>
        {page.quote && (
          <blockquote>
            “{page.quote.text}”
            <cite>
              {page.quote.agent} ({page.quote.model}), epoch {page.quote.epoch}
            </cite>
          </blockquote>
        )}
        <a className="small" href={page.link}>
          See the evidence →
        </a>
      </div>
    </article>
  );
}
