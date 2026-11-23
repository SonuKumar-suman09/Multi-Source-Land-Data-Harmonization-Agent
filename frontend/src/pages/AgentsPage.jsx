import { useCallback, useEffect, useState } from "react";
import { Activity, CircleAlert, Clock3, RefreshCw, Workflow } from "lucide-react";
import { apiRequest } from "../services/api.js";

const agentLabels = {
  workflow_orchestrator: "Workflow orchestrator",
  ingestion: "Data ingestion agent",
  harmonization: "Data harmonization agent",
  quality_assurance: "Quality assurance agent",
};

export default function AgentsPage() {
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState("");
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      const summary = await apiRequest("/api/v1/dashboard/summary");
      setJobs(summary.recent_jobs || []);
      const chosen = jobId || summary.recent_jobs?.[0]?.id || "";
      if (chosen) {
        setJobId(chosen);
        setReport(await apiRequest(`/api/v1/reports/jobs/${chosen}`));
      } else setReport(null);
      setError("");
    } catch (problem) { setError(problem.message); }
    finally { setLoading(false); }
  }, [jobId]);
  useEffect(() => { refresh(); const timer = window.setInterval(refresh, 10000); return () => window.clearInterval(timer); }, [refresh]);

  const executions = report?.agent_executions || [];
  const latestByAgent = new Map();
  for (const item of executions) latestByAgent.set(item.agent_name, item);
  const expectedAgents = ["workflow_orchestrator", "ingestion", "harmonization", "quality_assurance"];
  return <>
    <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> WORKFLOW OPERATIONS</div><h1>Agent activity</h1><p>See persisted agent runs, attempts, timing, and failures for each dataset.</p></div><button className="button button-outline" onClick={refresh}><RefreshCw size={15} /> Refresh</button></div>
    <section className="panel report-panel" style={{ marginBottom: 18 }}><label className="field-label">Dataset<select className="text-input" value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Select a dataset</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.source_name} · {job.status}</option>)}</select></label></section>
    {error && <div className="inline-notice notice-error">Could not load execution history: {error}</div>}
    {loading && !report ? <div className="panel loading-screen loading-compact">Loading agent history…</div> : !report ? <div className="panel subtle-empty">No datasets have been processed yet.</div> : <>
      <section className="metric-grid">
        <Metric label="Workflow" value={report.status.replaceAll("_", " ")} icon={Workflow} />
        <Metric label="Recorded runs" value={executions.length} icon={Activity} />
        <Metric label="Failures" value={executions.filter((run) => run.status === "failed").length} icon={CircleAlert} />
        <Metric label="Processing time" value={report.processing_time_ms == null ? "—" : `${Math.round(report.processing_time_ms)} ms`} icon={Clock3} />
      </section>
      <section className="panel report-panel" style={{ marginTop: 18 }}><div className="report-panel-heading"><div><span className="panel-kicker">SPECIALIZED AGENTS</span><h2>Execution status</h2></div><span>Refreshes every 10 seconds</span></div>
        <div className="execution-list">{expectedAgents.map((name) => { const run = latestByAgent.get(name); return <article className="execution-row" key={name}><span className={`execution-mark ${run?.status === "failed" ? "execution-failed" : run?.status === "queued" || run?.status === "running" ? "execution-running" : ""}`}><Activity size={15} /></span><div className="execution-copy"><b>{agentLabels[name]}</b><span>{run ? `${run.status.replaceAll("_", " ")} · attempt ${run.attempt}` : "No separate run row recorded for this node"}{run?.error_code ? ` · ${run.error_code}` : ""}</span></div><small>{run?.duration_ms == null ? "—" : `${Math.round(run.duration_ms)} ms`}</small></article>; })}</div>
        {executions.some((run) => run.error_code) && <div className="inline-notice notice-warning">One or more agent runs recorded an error. Open Reports & audit for the complete execution and audit details.</div>}
      </section>
    </>}
  </>;
}

function Metric({ label, value, icon: Icon }) { return <article className="metric-card"><span className="metric-icon metric-blue"><Icon size={16} /></span><small className="metric-label">{label}</small><b className="metric-value" style={{ fontSize: 22, textTransform: "capitalize" }}>{value}</b></article>; }
