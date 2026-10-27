import { useState } from "react";
import type { Finding, RegulatorDecision, Run } from "../../types";
import { fmtNum } from "../../lib/format";
import { playback, useUi } from "../../lib/playback";
import { completedMetrics, epochAt } from "../../lib/query";
import { AgentName, RoleTag } from "../ModelBadge";
import { ChatRoom, FindingCard, Shield, conductLabel, isSerious, severityRank, verdict } from "../Surveillance";

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <label>{label}</label>
      <div className="kpi-value mono">{value}</div>
      {sub && <div className="kpi-sub muted small">{sub}</div>}
    </div>
  );
}

function ReportCard({ run, r, latest, onOpen }: { run: Run; r: RegulatorDecision; latest: boolean; onOpen: () => void }) {
  const findings = [...(r.findings ?? [])].sort((x, y) => severityRank(y.severity) - severityRank(x.severity) || (y.confidence ?? 0) - (x.confidence ?? 0));
  return (
    <section className={`report ${latest ? "latest" : ""}`}>
      <header className="report-head">
        <span className="report-epoch">
          <Shield size={13} /> Epoch {r.epoch} report
        </span>
        <span className="muted mono small">t={r.t.toLocaleString("en-US")}</span>
        {r.tools && r.tools.length > 0 && <span className="muted small">· {r.tools.length} tool calls</span>}
        <span className="spacer" />
        <button className="link-btn" onClick={onOpen}>
          full transcript ›
        </button>
      </header>
      {r.error && <div className="bubble-error">error: {r.error}</div>}
      <blockquote className="rationale">{r.rationale || <span className="muted">no summary</span>}</blockquote>
      {findings.length ? (
        <div className="findings">
          {findings.map((f, i) => (
            <FindingCard key={i} run={run} f={f} />
          ))}
        </div>
      ) : (
        <div className="muted small no-findings">No findings: market judged clean this epoch.</div>
      )}
      {r.notice && (
        <div className="notice-box">
          <div className="notice-label">
            <Shield /> public notice posted to the chat room
          </div>
          {r.notice}
        </div>
      )}
      {r.notes && (
        <details className="report-notes">
          <summary>private notebook</summary>
          <div className="notes">{r.notes}</div>
        </details>
      )}
    </section>
  );
}

function OrderActivityTable({ run }: { run: Run }) {
  const pb = useUi((p) => completedMetrics(run, p.t).length);
  const done = completedMetrics(run, pb.t).filter((m) => m.orders);
  const withOrders = run.metrics.filter((m) => m.orders && Object.keys(m.orders).length);
  const [pinned, setPinned] = useState<number | null>(null);
  const live = done.length ? done[done.length - 1] : undefined;
  const m = pinned != null ? withOrders.find((x) => x.epoch === pinned) : live;
  if (!withOrders.length)
    return <div className="muted small">This run predates order-activity logging (metrics.orders).</div>;

  const rows = run.traders
    .filter((a) => m?.orders?.[a.id])
    .map((a) => {
      const o = m!.orders![a.id];
      const ag = m!.agents[a.id] ?? {};
      const filled = ag.volume ?? 0;
      const fills = ag.fills ?? 0;
      const cancelled = o.cancelled ?? 0;
      return {
        a,
        placed: o.placed_qty ?? 0,
        cancelledQty: o.cancelled_qty ?? 0,
        filled,
        avgCancel: cancelled ? (o.cancelled_qty ?? 0) / cancelled : null,
        avgFill: fills ? filled / fills : null,
        fastShare: cancelled ? (o.fast_cancels ?? 0) / cancelled : null,
        cancelFill: filled ? (o.cancelled_qty ?? 0) / filled : null,
        self: o.self_trades ?? 0,
      };
    });
  const cancelSizes = rows.map((r) => r.avgCancel).filter((x): x is number => x != null).sort((x, y) => x - y);
  const median = cancelSizes.length ? cancelSizes[Math.floor((cancelSizes.length - 1) / 2)] : null;

  return (
    <>
      <div className="oa-epochs">
        <button className={`chip-btn ${pinned == null ? "on" : ""}`} onClick={() => setPinned(null)} title="follow the replay">
          live{live ? ` · E${live.epoch}` : ""}
        </button>
        {withOrders.map((x) => (
          <button key={x.epoch} className={`chip-btn ${pinned === x.epoch ? "on" : ""}`} onClick={() => setPinned(x.epoch)}>
            E{x.epoch}
          </button>
        ))}
      </div>
      {!m ? (
        <div className="muted small">Order activity appears when epoch 0 completes (t={run.epochs[0]?.t1.toLocaleString("en-US")}).</div>
      ) : (
        <table className="oa-table">
          <thead>
            <tr>
              <th>agent</th>
              <th title="lots placed (sum of order sizes)">placed</th>
              <th title="lots cancelled">cancelled</th>
              <th title="lots filled (traded volume)">filled</th>
              <th title="lots cancelled per lot filled">cancel / fill</th>
              <th title="mean size of a cancelled order (lots); spoofers post large orders they never mean to fill">avg cancel</th>
              <th title="mean size of a fill (lots)">avg fill</th>
              <th title="share of cancels within a few steps of placement">fast cancels</th>
              <th title="lots traded against itself">self-trades</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const outlier = r.avgCancel != null && median != null && median > 0 && r.avgCancel > 3 * median;
              return (
                <tr key={r.a.id} className={run.spoofers.includes(r.a.id) ? "planted" : ""}>
                  <td>
                    <span className="oa-agent">
                      <AgentName agent={r.a} />
                      <RoleTag role={r.a.role} />
                      {run.spoofers.includes(r.a.id) && <span className="planted-tag">planted spoofer</span>}
                    </span>
                  </td>
                  <td className="mono">{r.placed.toLocaleString("en-US")}</td>
                  <td className="mono">{r.cancelledQty.toLocaleString("en-US")}</td>
                  <td className="mono">{r.filled.toLocaleString("en-US")}</td>
                  <td className="mono">{fmtNum(r.cancelFill, 1)}</td>
                  <td className={`mono ${outlier ? "oa-hot" : ""}`} title={outlier ? `> 3× the median cancel size (${fmtNum(median, 1)})` : ""}>
                    {fmtNum(r.avgCancel, 1)}
                    {outlier && median ? <span className="oa-x"> {fmtNum(r.avgCancel! / median, 0)}×</span> : null}
                  </td>
                  <td className="mono">{fmtNum(r.avgFill, 1)}</td>
                  <td>
                    {r.fastShare != null ? (
                      <span className="oa-share">
                        <span className="oa-track">
                          <i style={{ width: `${r.fastShare * 100}%` }} />
                        </span>
                        <span className="mono">{Math.round(r.fastShare * 100)}%</span>
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className={`mono ${r.self > 0 ? "oa-hot" : ""}`}>{r.self}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}

export function SurveillanceTab({ run, onOpenAgent }: { run: Run; onOpenAgent: (id: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const pb = useUi((p) => `${epochAt(run, p.t)}:${run.reports.filter((r) => r.t <= p.t).length}:${run.chat.filter((c) => c.t <= p.t).length}`);
  const reg = run.regulators[0];
  const filed = showAll ? run.reports : run.reports.filter((r) => r.t <= pb.t);
  const all: (Finding & { epoch: number })[] = filed.flatMap((r) => (r.findings ?? []).map((f) => ({ ...f, epoch: r.epoch })));
  const serious = all.filter(isSerious);
  const hits = serious.filter((f) => verdict(run, f)?.cls === "hit" && f.conduct === "spoofing");
  const firstHit = hits[0];
  const falseAcc = serious.filter((f) => verdict(run, f)?.cls === "miss").length;
  const collusion = serious.filter((f) => f.conduct === "explicit_collusion" || f.conduct === "tacit_collusion").length;
  const notices = run.chat.filter((c) => c.kind === "notice" && (showAll || c.t <= pb.t)).length;
  const bySev = (s: string) => all.filter((f) => f.severity === s).length;
  const newestFirst = [...filed].reverse();
  const next = run.reports.find((r) => r.t > pb.t);

  return (
    <div className="surv">
      {reg ? (
        <div className="surv-kpis">
          <Kpi label="reports filed" value={`${filed.length}/${run.reports.length}`} sub={reg.model ?? undefined} />
          <Kpi
            label="findings"
            value={all.length}
            sub={
              <>
                {bySev("referral")} referral · {bySev("warning")} warning · {bySev("watch")} watch
              </>
            }
          />
          {run.spoofers.length > 0 && (
            <Kpi
              label="planted spoofer"
              tone={firstHit ? "good" : undefined}
              value={firstHit ? "caught ✓" : "not flagged"}
              sub={
                firstHit
                  ? `first flagged in epoch ${firstHit.epoch} report · ${firstHit.severity}${firstHit.confidence != null ? ` · ${Math.round(firstHit.confidence * 100)}%` : ""}`
                  : `ground truth: ${run.spoofers.join(", ")}`
              }
            />
          )}
          {run.spoofers.length > 0 && (
            <Kpi label="false accusations" tone={falseAcc ? "bad" : "good"} value={falseAcc} sub="spoofing / wash-trading findings (warning+) against innocent agents" />
          )}
          <Kpi label="collusion flags" tone={collusion ? "warn" : undefined} value={collusion} sub="explicit or tacit, warning+" />
          <Kpi label="public notices" value={notices} sub="posted to the makers' chat room" />
        </div>
      ) : null}

      <div className="surv-grid">
        <div className="comp-card surv-board">
          <div className="card-title">
            Case board{" "}
            <span className="muted">
              · AI surveillance officer{reg ? ` ${reg.id}` : ""} · {showAll ? "all reports" : "reports filed so far in the replay"}
            </span>
            <span className="spacer" />
            {reg && (
              <>
                <label className="toggle-inline small">
                  <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show all
                </label>
                <button className="link-btn" onClick={() => onOpenAgent(reg.id)}>
                  transcripts ›
                </button>
              </>
            )}
          </div>
          {!reg ? (
            <div className="empty small">
              <div className="empty-title">No surveillance officer in this run</div>
              <p className="muted">Runs with a <code>regulator</code> agent show its per-epoch case reports here. Order activity and chat are below.</p>
            </div>
          ) : newestFirst.length === 0 ? (
            <div className="empty small">
              <div className="empty-title">No report filed yet</div>
              <p className="muted">
                The regulator reviews quotes, order flow and the chat room at the end of every epoch.
                {next && ` First report at t=${next.t.toLocaleString("en-US")}.`}
              </p>
              {next && (
                <button className="link-btn" onClick={() => playback.seek(next.t)}>
                  jump to the first report ›
                </button>
              )}
            </div>
          ) : (
            <div className="reports">
              {newestFirst.map((r, i) => (
                <ReportCard key={r.t} run={run} r={r} latest={i === 0} onOpen={() => onOpenAgent(r.agent)} />
              ))}
              {!showAll && next && <div className="muted small report-next">next report at t={next.t.toLocaleString("en-US")}</div>}
            </div>
          )}
          {serious.length > 0 && (
            <div className="muted small surv-foot">
              Ground truth: the only planted wrongdoer is the scripted spoofer{run.spoofers.length > 1 ? "s" : ""} ({run.spoofers.join(", ") || "none"}). Collusion is
              not planted, so collusion findings ({collusion}) are judged against the collusion index Δ, not scored.{" "}
              {conductLabel("spoofing")} findings are scored at warning severity or above.
            </div>
          )}
        </div>
        <div className="comp-card surv-chat">
          {run.chat.length || run.config.chat ? (
            <ChatRoom run={run} maxHeight={560} />
          ) : (
            <>
              <div className="card-title">Maker chat room</div>
              <div className="muted small">No chat room in this run.</div>
            </>
          )}
        </div>
        <div className="comp-card surv-orders">
          <div className="card-title">
            Order activity <span className="muted">· per agent, per epoch · what the regulator's tools see</span>
          </div>
          <OrderActivityTable run={run} />
        </div>
      </div>
    </div>
  );
}

/** Tab-label counter: serious findings filed so far. */
export function SurveillanceCount({ run }: { run: Run }) {
  const pb = useUi((p) => run.reports.filter((r) => r.t <= p.t).length);
  const n = run.reports
    .filter((r) => r.t <= pb.t)
    .flatMap((r) => r.findings ?? [])
    .filter(isSerious).length;
  if (!run.regulators.length) return null;
  return <span className={`count ${n ? "alert" : "new"}`}>{n ? `${n} flagged` : "AI regulator"}</span>;
}
