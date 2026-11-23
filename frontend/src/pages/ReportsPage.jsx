import { useEffect, useState } from "react";
import {
  Activity, ArrowDownToLine, FileSpreadsheet, FileText,
  LoaderCircle, ShieldCheck, TriangleAlert,
} from "lucide-react";
import { apiRequest, downloadReport } from "../services/api.js";

export default function ReportsPage() {
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState("");
  const [report, setReport] = useState(null);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [downloading, setDownloading] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest("/api/v1/dashboard/summary")
      .then((summary) => {
        const recent = summary.recent_jobs || [];
        setJobs(recent);
        setJobId(recent[0]?.id || "");
      })
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoadingJobs(false));
  }, []);

  useEffect(() => {
    if (!jobId) { setReport(null); return; }
    const controller = new AbortController();
    setLoadingReport(true);
    setError("");
    apiRequest(`/api/v1/reports/jobs/${jobId}`, { signal: controller.signal })
      .then(setReport)
      .catch((requestError) => {
        if (requestError.name !== "AbortError") setError(requestError.message);
      })
      .finally(() => { if (!controller.signal.aborted) setLoadingReport(false); });
    return () => controller.abort();
  }, [jobId]);

  const download = async (format) => {
    if (!jobId) return;
    setDownloading(format);
    setError("");
    try {
      await downloadReport(`/api/v1/reports/jobs/${jobId}/${format}`, `land-report-${jobId}.${format}`);
    } catch (downloadError) {
      setError(downloadError.message);
    } finally {
      setDownloading("");
    }
  };

  const selectedJob = jobs.find((job) => job.id === jobId);
  return (
    <>
      <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> PROCESSING RECORDS</div><h1>Reports & audit</h1><p>Download the result and review how this dataset moved through the workflow.</p></div><div className="report-downloads"><button className="button button-outline" onClick={() => download("csv")} disabled={!report || Boolean(downloading)}><FileSpreadsheet size={15} />{downloading === "csv" ? "Preparing…" : "Download CSV"}</button><button className="button button-primary" onClick={() => download("pdf")} disabled={!report || Boolean(downloading)}><ArrowDownToLine size={15} />{downloading === "pdf" ? "Preparing…" : "Download PDF"}</button></div></div>
      {error && <div className="inline-notice notice-error" role="alert"><TriangleAlert size={15} />{error}<button className="notice-action" onClick={() => setError("")}>Dismiss</button></div>}
      {loadingJobs ? <div className="panel report-empty"><LoaderCircle className="spin" size={19} />Loading your dataset history…</div> : jobs.length === 0 ? <div className="panel report-empty"><FileText size={23} /><b>No processing reports yet</b><span>Upload and harmonize a dataset to create its first report.</span></div> : <>
        <section className="panel report-picker"><div><span className="panel-kicker">SELECT DATASET</span><b>{jobs.length} recent job{jobs.length === 1 ? "" : "s"}</b></div><label><span className="sr-only">Choose a dataset report</span><select value={jobId} onChange={(event) => setJobId(event.target.value)}>{jobs.map((job) => <option key={job.id} value={job.id}>{job.source_name} · {new Date(job.created_at).toLocaleDateString()}</option>)}</select></label></section>
        {loadingReport ? <div className="panel report-empty"><LoaderCircle className="spin" size={19} />Loading report and audit history…</div> : report && <>
          <div className="report-job-title"><div><span className="panel-kicker">{report.source_name}</span><h2>{selectedJob?.source_name || report.source_name}</h2><small>Job {report.job_id} · {new Date(report.created_at).toLocaleString()}</small></div><span className={`status-badge status-${report.status.replaceAll("_", "-")}`}><i />{report.status.replaceAll("_", " ")}</span></div>
          <section className="report-stat-grid">
            <ReportStat label="Processed" value={report.harmonized_records} detail={`${report.total_records} raw source rows`} icon={FileSpreadsheet} />
            <ReportStat label="Valid" value={report.valid_records} detail={`${report.invalid_records} invalid`} icon={ShieldCheck} />
            <ReportStat label="Review and conflicts" value={report.review_records + report.conflict_records} detail={`${report.duplicate_pairs} duplicate pairs`} icon={TriangleAlert} />
            <ReportStat label="Quality score" value={report.quality_score == null ? "—" : `${Number(report.quality_score).toFixed(1)}%`} detail={report.processing_time_ms == null ? "Processing time unavailable" : `${formatDuration(report.processing_time_ms)} total`} icon={Activity} />
          </section>
          <div className="report-content-grid">
            <section className="panel report-panel"><div className="report-panel-heading"><div><span className="panel-kicker">WORKFLOW</span><h2>Agent execution</h2></div><span>{report.agent_executions.length} runs</span></div>
              {report.agent_executions.length ? <div className="execution-list">{report.agent_executions.map((execution) => <div className="execution-row" key={execution.id}><span className={`execution-mark execution-${execution.status}`}><Activity size={14} /></span><div className="execution-copy"><b>{execution.agent_name.replaceAll("_", " ")}</b><span>{execution.status}{execution.attempt > 1 ? ` · attempt ${execution.attempt}` : ""}{execution.error_code ? ` · ${execution.error_code}` : ""}</span></div><small>{execution.duration_ms == null ? "—" : formatDuration(execution.duration_ms)}</small></div>)}</div> : <div className="subtle-empty">No agent executions recorded.</div>}
            </section>
            <section className="panel report-panel"><div className="report-panel-heading"><div><span className="panel-kicker">SOURCES</span><h2>Original files</h2></div><span>{report.source_files.length}</span></div>
              {report.source_files.length ? <div className="source-file-list">{report.source_files.map((file) => <div className="source-file-row" key={file.id}><span><FileSpreadsheet size={15} /></span><div><b>{file.filename}</b><small>{(file.format || "file").toUpperCase()} · {formatBytes(file.size_bytes)}</small></div></div>)}</div> : <div className="subtle-empty">No source files recorded.</div>}
            </section>
          </div>
          <section className="panel audit-panel"><div className="report-panel-heading"><div><span className="panel-kicker">PROVENANCE</span><h2>Audit history</h2></div><span>{report.audit_events.length} events</span></div>
            {report.audit_events.length ? <div className="audit-list">{report.audit_events.map((event) => <div className="audit-event" key={event.id}><span className="audit-line"><i /></span><div><b>{event.action.replaceAll(".", " ")}</b><small>{event.actor_email || "System"}</small></div><time>{new Date(event.created_at).toLocaleString()}</time></div>)}</div> : <div className="subtle-empty">No audit events recorded for this job.</div>}
          </section>
          <section className="panel findings-panel"><div className="report-panel-heading"><div><span className="panel-kicker">QUALITY</span><h2>Validation findings</h2></div><span>{report.findings.length} listed · {Object.values(report.severity_counts).reduce((sum, count) => sum + count, 0)} total</span></div>
            {report.findings.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>SEVERITY</th><th>RULE</th><th>RECORD</th><th>FINDING</th><th>RECOMMENDED ACTION</th></tr></thead><tbody>{report.findings.map((finding, index) => <tr key={`${finding.code}-${finding.record_id}-${index}`}><td><span className={`severity-chip severity-${finding.severity}`}>{finding.severity}</span></td><td>{finding.code}</td><td>{finding.record_id ? finding.record_id.slice(0, 8) : "—"}</td><td>{finding.message}</td><td>{finding.suggested_action || "Review source record"}</td></tr>)}</tbody></table></div> : <div className="subtle-empty">No validation findings were recorded.</div>}
          </section>
        </>}
      </>}
    </>
  );
}

function ReportStat({ label, value, detail, icon: Icon }) {
  return <div className="report-stat"><span><Icon size={16} /></span><small>{label}</small><b>{value}</b><em>{detail}</em></div>;
}

function formatDuration(milliseconds) {
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(2)} s`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
