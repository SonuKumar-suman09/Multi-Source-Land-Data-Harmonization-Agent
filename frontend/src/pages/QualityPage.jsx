import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleAlert, Info, RefreshCw, ShieldCheck } from "lucide-react";
import { apiRequest } from "../services/api.js";

export default function QualityPage() {
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState("");
  const [report, setReport] = useState(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      const summary = await apiRequest("/api/v1/dashboard/summary");
      setJobs(summary.recent_jobs || []);
      const chosen = jobId || summary.recent_jobs?.[0]?.id || "";
      if (chosen) { setJobId(chosen); setReport(await apiRequest(`/api/v1/reports/jobs/${chosen}`)); }
      else setReport(null);
      setError("");
    } catch (problem) { setError(problem.message); }
    finally { setLoading(false); }
  }, [jobId]);
  useEffect(() => { refresh(); }, [refresh]);
  const findings = (report?.findings || []).filter((finding) => filter === "all" || finding.severity === filter);
  return <>
    <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> VALIDATION REVIEW</div><h1>Data quality</h1><p>Inspect persisted validation findings and decide what needs review in the original source.</p></div><button className="button button-outline" onClick={refresh}><RefreshCw size={15} /> Refresh</button></div>
    <section className="panel report-panel" style={{ marginBottom: 18 }}><label className="field-label">Dataset<select className="text-input" value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Select a dataset</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.source_name} · {job.status}</option>)}</select></label></section>
    {error && <div className="inline-notice notice-error">Could not load quality findings: {error}</div>}
    {loading && !report ? <div className="panel loading-screen loading-compact">Loading validation results…</div> : !report ? <div className="panel subtle-empty">No datasets have been processed yet.</div> : <>
      <section className="metric-grid">
        <QualityMetric label="Quality score" value={report.quality_score == null ? "—" : `${Number(report.quality_score).toFixed(1)}%`} icon={ShieldCheck} />
        <QualityMetric label="Valid" value={report.valid_records} icon={CheckCircle2} />
        <QualityMetric label="Needs review" value={report.review_records + report.conflict_records} icon={AlertTriangle} />
        <QualityMetric label="Findings" value={Object.values(report.severity_counts || {}).reduce((sum, count) => sum + count, 0)} icon={CircleAlert} />
      </section>
      <section className="panel findings-panel" style={{ marginTop: 18 }}><div className="report-panel-heading"><div><span className="panel-kicker">SOURCE-BASED REVIEW</span><h2>Validation findings</h2></div><select className="text-input" style={{ width: 170 }} value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All severities</option><option value="critical">Critical errors</option><option value="warning">Warnings</option><option value="info">Information</option></select></div>
        {findings.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>SEVERITY</th><th>RULE</th><th>RECORD</th><th>FINDING</th><th>SUGGESTED ACTION</th></tr></thead><tbody>{findings.map((item, index) => <tr key={`${item.code}-${item.record_id}-${index}`}><td><span className={`severity-chip severity-${item.severity}`}>{item.severity}</span></td><td>{item.code}</td><td>{item.record_id ? item.record_id.slice(0, 8) : "—"}</td><td>{item.message}</td><td>{item.suggested_action || "Review original source"}</td></tr>)}</tbody></table></div> : <div className="subtle-empty">No findings match this filter.</div>}
        <div className="dashboard-note" style={{ margin: 16 }}><Info size={15} /> This screen reports findings. It does not edit source values; correct the original data and upload a new version to preserve the audit trail.</div>
      </section>
    </>}
  </>;
}

function QualityMetric({ label, value, icon: Icon }) { return <article className="metric-card"><span className="metric-icon metric-green"><Icon size={16} /></span><small className="metric-label">{label}</small><b className="metric-value" style={{ fontSize: 22 }}>{value}</b></article>; }
