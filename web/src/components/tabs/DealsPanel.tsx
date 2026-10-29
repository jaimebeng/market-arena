/** AI investment banking in the Wind Tunnel: each seed's IPO (the AI underwriter's range, offer and
 * book against the company's hidden value) and each structured note the AI desk invented. */

type Ipo = {
  company: string;
  lots_offered: number;
  range: [number, number];
  offer: number;
  value_at_filing: number;
  value_at_listing: number;
  covered: number;
  underpricing_pct: number;
  first_epoch_return_pct: number;
  bank_kept_lots: number;
  allocations: Record<string, number>;
  rationale?: string | null;
};
type Note = {
  id: string;
  name: string;
  formula: string;
  description: string;
  issue_price: number;
  model_value: number;
  markup_pct: number | null;
  headline_max_payoff: number;
  complexity: number;
  quarters: number;
  chance_loss?: number;
  sold: number;
  payoff: number | null;
};
type SeedRun = { run?: string; ipo_detail?: Ipo; notes_detail?: Note[] };

const seed = (run?: string) => (run ?? "").split("/").filter(Boolean).pop() ?? "";
const sgn = (x: number, d = 1) => `${x > 0 ? "+" : ""}${x.toFixed(d)}`;

export function DealsPanel({ runs, label }: { runs: SeedRun[]; label: string }) {
  const ipos = runs.filter((r) => r.ipo_detail);
  const notes = runs.filter((r) => r.notes_detail?.length);
  if (!ipos.length && !notes.length) return null;
  return (
    <div className="comp-card deals">
      {ipos.length > 0 && (
        <>
          <div className="card-title">
            The IPOs <span className="muted">· {label}: the AI underwriter's range and offer against the company's hidden value</span>
          </div>
          <div className="exam-scroll">
            <table className="deals-table">
              <thead>
                <tr>
                  <th>seed</th>
                  <th>company (named by the AI founder)</th>
                  <th>range ¢</th>
                  <th>offer ¢</th>
                  <th>true value ¢</th>
                  <th>underpriced</th>
                  <th>after listing</th>
                  <th>book</th>
                  <th>bank kept</th>
                  <th>the underwriter's reasoning</th>
                </tr>
              </thead>
              <tbody>
                {ipos.map((r) => {
                  const p = r.ipo_detail!;
                  return (
                    <tr key={r.run}>
                      <td className="mono">{seed(r.run)}</td>
                      <td>{p.company}</td>
                      <td className="mono">
                        {p.range[0].toFixed(0)}–{p.range[1].toFixed(0)}
                      </td>
                      <td className="mono">{p.offer.toFixed(0)}</td>
                      <td className="mono">{p.value_at_listing.toFixed(0)}</td>
                      <td className={`mono ${p.underpricing_pct > 0 ? "pos" : "neg"}`}>{sgn(p.underpricing_pct)}%</td>
                      <td className={`mono ${p.first_epoch_return_pct > 0 ? "pos" : "neg"}`}>{sgn(p.first_epoch_return_pct)}%</td>
                      <td className="mono">{p.covered.toFixed(1)}×</td>
                      <td className="mono">{p.bank_kept_lots}</td>
                      <td className="small muted">{(p.rationale ?? "").slice(0, 220)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="wt-caption">
            Underpriced: the company's true value at listing over the offer price. After listing: the market price one quarter
            later over the offer. Book: demand at the offer price over the lots offered. Everyone priced from a noisy estimate;
            only the simulator knows the true value.
          </div>
        </>
      )}
      {notes.length > 0 && (
        <>
          <div className="card-title">
            The notes <span className="muted">· {label}: instruments the AI structuring desk invented, priced on the bank's own model</span>
          </div>
          <div className="exam-scroll">
            <table className="deals-table">
              <thead>
                <tr>
                  <th>seed</th>
                  <th>note</th>
                  <th>payoff per $100 (the desk's formula)</th>
                  <th>price $</th>
                  <th>worth $</th>
                  <th>markup</th>
                  <th>best case $</th>
                  <th>chance of a loss</th>
                  <th>sold</th>
                  <th>paid $</th>
                </tr>
              </thead>
              <tbody>
                {notes.flatMap((r) =>
                  r.notes_detail!.map((n) => (
                    <tr key={`${r.run}-${n.id}`}>
                      <td className="mono">{seed(r.run)}</td>
                      <td title={n.description}>
                        <b>{n.name}</b>
                        <div className="small muted">{n.description.slice(0, 160)}</div>
                      </td>
                      <td className="mono small deals-formula">{n.formula}</td>
                      <td className="mono">{n.issue_price.toFixed(2)}</td>
                      <td className="mono">{n.model_value.toFixed(2)}</td>
                      <td className="mono">{n.markup_pct == null ? "—" : `${sgn(n.markup_pct)}%`}</td>
                      <td className="mono">{n.headline_max_payoff.toFixed(0)}</td>
                      <td className="mono">{n.chance_loss == null ? "—" : `${Math.round(n.chance_loss * 100)}%`}</td>
                      <td className="mono">{n.sold}</td>
                      <td className="mono">{n.payoff == null ? "—" : n.payoff.toFixed(2)}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
          <div className="wt-caption">
            Worth: the bank's Monte Carlo value of the note on the day it was issued. Markup: price over worth, the desk's
            profit on each note sold. Best case: the 99th-percentile payoff, the "headline" retail sees. Chance of a loss: the
            model's probability that the note pays back less than its price.
          </div>
        </>
      )}
    </div>
  );
}
