import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import {
  ArrowDownToLine, ArrowRight, Check, ChevronDown, CircleHelp, FileText,
  Database, Files, FolderUp, Globe2, KeyRound, LandPlot, LoaderCircle,
  LogOut, Map as MapIcon, MapPinned, Menu, Plus, ShieldCheck, Sparkles, Upload,
  X, TriangleAlert,
} from "lucide-react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { apiRequest, clearSession, getToken, saveSession, uploadFiles } from "./services/api.js";

const DashboardCharts = lazy(() => import("./components/DashboardCharts.jsx"));
const MapPage = lazy(() => import("./pages/MapPage.jsx"));
const ReportsPage = lazy(() => import("./pages/ReportsPage.jsx"));

const sections = [
  { to: "/", label: "Overview", icon: LandPlot, end: true },
  { to: "/upload", label: "Upload datasets", icon: FolderUp },
  { to: "/map", label: "Parcel map", icon: MapIcon },
  { to: "/reports", label: "Reports & audit", icon: FileText },
];

export default function App() {
  const [auth, setAuth] = useState({ user: null, loading: Boolean(getToken()) });
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    if (!getToken()) return;
    apiRequest("/api/v1/auth/me")
      .then((user) => setAuth({ user, loading: false }))
      .catch((error) => {
        clearSession();
        setAuth({ user: null, loading: false });
        setAuthError(error.message === "Failed to fetch" ? "API connection is unavailable." : "Your session ended. Please sign in again.");
      });
  }, []);

  if (auth.loading) return <LoadingScreen label="Restoring your workspace" />;
  if (!auth.user) {
    return <AuthPage onAuthenticated={(user) => { setAuth({ user, loading: false }); setAuthError(""); }} initialError={authError} />;
  }
  return (
    <Routes>
      <Route element={<ProtectedLayout user={auth.user} onLogout={() => { clearSession(); setAuth({ user: null, loading: false }); }} />}>
        <Route index element={<DashboardPage user={auth.user} />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="map" element={<Suspense fallback={<LoadingScreen label="Loading parcel map" compact />}><MapPage /></Suspense>} />
        <Route path="reports" element={<Suspense fallback={<LoadingScreen label="Loading reports" compact />}><ReportsPage /></Suspense>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AuthPage({ onAuthenticated, initialError }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError || "");
  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const endpoint = mode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register";
      const session = await apiRequest(endpoint, { method: "POST", body: JSON.stringify({ email, password }) });
      saveSession(session.access_token, session.user);
      onAuthenticated(session.user);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <div className="auth-aside">
        <div className="brand brand-light"><span className="brand-symbol"><LandPlot size={19} /></span> TERRAFORM <span className="brand-tag">LAND DATA</span></div>
        <div className="auth-story">
          <div className="eyebrow eyebrow-light"><span className="eyebrow-dot" /> LAND RECORDS · ONE WORKSPACE</div>
          <h1>Bring every parcel record into focus.</h1>
          <p>Harmonize files from different sources, validate what matters, and keep every transformation traceable.</p>
          <div className="auth-proof"><ShieldCheck size={17} /> Provenance stays connected to every record.</div>
        </div>
        <div className="auth-foot">Synthetic demo data only · 2026</div>
      </div>
      <section className="auth-main">
        <div className="auth-card">
          <span className="auth-kicker">YOUR DATA WORKSPACE</span>
          <h2>{mode === "login" ? "Welcome back" : "Create your workspace"}</h2>
          <p className="muted">{mode === "login" ? "Sign in to continue where you left off." : "One account creates a private workspace for your land datasets."}</p>
          <div className="auth-switch" role="tablist" aria-label="Account action">
            <button className={mode === "login" ? "selected" : ""} onClick={() => { setMode("login"); setError(""); }}>Sign in</button>
            <button className={mode === "register" ? "selected" : ""} onClick={() => { setMode("register"); setError(""); }}>Create account</button>
          </div>
          <form onSubmit={submit} className="auth-form">
            <label>Email address<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@organization.org" autoComplete="email" required /></label>
            <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "register" ? "At least 12 characters" : "Enter your password"} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "register" ? 12 : 1} required /></label>
            {error && <InlineNotice tone="error">{error}</InlineNotice>}
            <button className="button button-primary auth-submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <KeyRound size={16} />}
              {busy ? "Connecting…" : mode === "login" ? "Sign in securely" : "Create secure workspace"}
              {!busy && <ArrowRight size={16} className="button-trailing" />}
            </button>
          </form>
          <div className="auth-security"><ShieldCheck size={15} /> Protected with signed sessions and workspace-scoped access.</div>
        </div>
        <div className="auth-footer">Multi-Source Land-Data Harmonization Agent <span>·</span> v0.1</div>
      </section>
    </main>
  );
}

function ProtectedLayout({ user, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const location = useLocation();
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <NavLink to="/" className="brand"><span className="brand-symbol"><LandPlot size={19} /></span><span>TERRAFORM</span></NavLink>
        <div className="workspace-switcher"><span className="workspace-mark">{user.email?.slice(0, 1).toUpperCase()}</span><span className="workspace-label"><small>WORKSPACE</small><b>My land records</b></span></div>
        <div className="nav-label">WORKSPACE</div>
        <nav className="side-nav">
          {sections.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setMobileNav(false)} className={({ isActive }) => `nav-item ${isActive ? "nav-active" : ""}`}><Icon size={17} strokeWidth={1.8} /><span>{label}</span>{label === "Upload datasets" && <span className="nav-plus"><Plus size={14} /></span>}</NavLink>)}
        </nav>
        <div className="nav-label nav-label-lower">YOUR PIPELINE</div>
        <div className="pipeline-step"><span className="step-number">01</span><span>Ingest sources</span></div>
        <div className="pipeline-step"><span className="step-number">02</span><span>Harmonize fields</span></div>
        <div className="pipeline-step"><span className="step-number">03</span><span>Quality review</span></div>
        <div className="sidebar-bottom"><div className="help-card"><div className="help-icon"><CircleHelp size={16} /></div><b>Source integrity</b><span>Original uploads remain unchanged</span><ShieldCheck size={14} /></div><div className="user-menu-wrap"><button className="user-menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><span className="avatar">{user.email?.slice(0, 1).toUpperCase()}</span><span className="user-info"><b>{user.email}</b><small>{user.role || "Analyst"}</small></span><ChevronDown size={15} /></button>{menuOpen && <div className="user-popover"><button onClick={onLogout}><LogOut size={15} /> Sign out</button></div>}</div></div>
      </aside>
      {mobileNav && <button className="nav-scrim" onClick={() => setMobileNav(false)} aria-label="Close navigation" />}
      <main className="main-shell">
        <header className="topbar"><button className="mobile-menu" onClick={() => setMobileNav(!mobileNav)} aria-label="Open menu"><Menu size={19} /></button><div className="breadcrumbs"><span>Workspace</span><span className="crumb-sep">/</span><b>{location.pathname === "/upload" ? "Upload datasets" : location.pathname === "/map" ? "Parcel map" : location.pathname === "/reports" ? "Reports & audit" : "Overview"}</b></div><div className="topbar-right"><div className="api-indicator"><span className="api-dot" /> Workspace metrics</div><button className="top-avatar" title={user.email}>{user.email?.slice(0, 1).toUpperCase()}</button></div></header>
        <div className="page-content"><Outlet /></div>
      </main>
    </div>
  );
}

function DashboardPage({ user }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      const data = await apiRequest("/api/v1/dashboard/summary");
      setSummary(data);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); const interval = window.setInterval(load, 15000); return () => window.clearInterval(interval); }, [load]);
  return (
    <>
      <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> YOUR LAND DATA, AT A GLANCE</div><h1>Good to see you, {user.email?.split("@")[0]}</h1><p>Track incoming datasets, harmonization, and review across your workspace.</p></div><NavLink to="/upload" className="button button-primary"><Upload size={16} /> Upload datasets</NavLink></div>
      {error && <InlineNotice tone="error">Dashboard data could not load: {error} <button className="notice-action" onClick={load}>Retry</button></InlineNotice>}
      {loading && !summary ? <LoadingScreen label="Loading workspace metrics" compact /> : <>
        <section className="metric-grid">
          <MetricCard label="Datasets" value={summary?.dataset_count ?? 0} detail={`${summary?.uploaded_file_count ?? 0} source files`} icon={Database} tone="green" />
          <MetricCard label="Source records" value={summary?.raw_record_count ?? 0} detail={`${summary?.harmonized_record_count ?? 0} harmonized`} icon={Files} tone="blue" />
          <MetricCard label="Valid records" value={summary?.valid_record_count ?? 0} detail={`${summary?.invalid_record_count ?? 0} invalid`} icon={ShieldCheck} tone="green" />
          <MetricCard label="Needs review" value={(summary?.review_record_count ?? 0) + (summary?.conflict_record_count ?? 0)} detail={`${summary?.duplicate_pair_count ?? 0} duplicate pairs`} icon={TriangleAlert} tone="amber" />
        </section>
        <Suspense fallback={<div className="chart-loading">Loading data visualizations…</div>}><DashboardCharts summary={summary} /></Suspense>
        <section className="panel recent-panel"><div className="panel-heading"><div><span className="panel-kicker">LATEST WORK</span><h2>Recent datasets</h2></div><NavLink to="/upload" className="text-link">Add a source <ArrowRight size={14} /></NavLink></div>
          {summary?.recent_jobs?.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>DATASET / SOURCE</th><th>STATUS</th><th>RECORDS</th><th>QUALITY</th><th>ADDED</th><th></th></tr></thead><tbody>{summary.recent_jobs.map((job) => <tr key={job.id}><td><span className="dataset-icon"><MapPinned size={16} /></span><span className="dataset-name"><b>{job.source_name}</b><small>{job.id.slice(0, 8)}…</small></span></td><td><StatusBadge status={job.status} /></td><td>{job.total_records.toLocaleString()}</td><td>{job.quality_score == null ? "—" : `${Number(job.quality_score).toFixed(1)}%`}</td><td>{new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(job.created_at))}</td><td><ArrowRight size={15} className="row-arrow" /></td></tr>)}</tbody></table></div> : <div className="empty-table"><div className="empty-icon"><FolderUp size={20} /></div><b>Your workspace is ready for its first dataset</b><span>Upload a CSV, Excel, GeoJSON, JSON, or zipped Shapefile.</span><NavLink to="/upload" className="button button-outline"><Upload size={15} /> Choose files</NavLink></div>}
        </section>
        <div className="dashboard-note"><Sparkles size={14} /> Quality values are generated from this workspace’s stored records. Review flagged fields before using land information.</div>
      </>}
    </>
  );
}

function UploadPage() {
  const [files, setFiles] = useState([]);
  const [sourceName, setSourceName] = useState("");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const pickFiles = (incoming) => {
    setError("");
    const allowed = /\.(csv|xlsx?|json|geojson|zip)$/i;
    const accepted = Array.from(incoming).filter((file) => allowed.test(file.name));
    setFiles((current) => [...current, ...accepted].filter((file, index, all) => all.findIndex((other) => other.name === file.name && other.size === file.size) === index));
    if (accepted.length !== incoming.length) setError("Some files were skipped. Choose CSV, Excel, JSON, GeoJSON, or zipped Shapefile files.");
  };
  const submit = async (event) => {
    event.preventDefault();
    if (!files.length) return setError("Add at least one supported file.");
    if (!sourceName.trim()) return setError("Enter a name for this source batch.");
    setError(""); setResult(null); setProgress(0); setBusy(true);
    try {
      const uploaded = await uploadFiles({ files, sourceName: sourceName.trim(), onProgress: setProgress });
      let queued = null;
      try { queued = await apiRequest(`/api/v1/workflows/jobs/${uploaded.job_id}/enqueue`, { method: "POST" }); }
      catch (queueError) { setError(`Files were uploaded successfully, but workflow queueing failed: ${queueError.message}`); }
      setResult({ ...uploaded, queued });
      setFiles([]);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> DATA INGESTION</div><h1>Bring in a source</h1><p>Upload files together when they belong to the same data batch.</p></div><button className="button button-quiet" onClick={() => navigate(-1)}><ArrowDownToLine size={15} className="rotate-back" /> Back to overview</button></div>
      <div className="upload-layout"><form className="panel upload-panel" onSubmit={submit}><div className="form-section-title"><span className="form-step">01</span><div><b>Source details</b><small>Help your team identify this batch later.</small></div></div>
        <label className="field-label">Source or batch name<input className="text-input" value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="e.g. North district parcel register" maxLength={200} /></label>
        <div className="form-section-title files-title"><span className="form-step">02</span><div><b>Select source files</b><small>Original files are preserved unchanged.</small></div></div>
        <div className={`dropzone ${dragging ? "dropzone-active" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); pickFiles(event.dataTransfer.files); }} onClick={() => document.getElementById("dataset-files")?.click()} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") document.getElementById("dataset-files")?.click(); }}>
          <input id="dataset-files" type="file" multiple accept=".csv,.xlsx,.xls,.json,.geojson,.zip" onChange={(event) => pickFiles(event.target.files)} hidden />
          <div className="drop-icon"><Upload size={21} /></div><b>Drop files here, or <span>browse</span></b><p>CSV · Excel · JSON · GeoJSON · Zipped Shapefile</p><small>Maximum combined upload size: 100 MB</small>
        </div>
        {files.length > 0 && <div className="selected-files"><div className="selected-files-heading">{files.length} file{files.length > 1 ? "s" : ""} selected<button type="button" onClick={() => setFiles([])}>Remove all</button></div>{files.map((file, index) => <div className="file-row" key={`${file.name}-${index}`}><span className="file-type">{file.name.split(".").pop().slice(0, 4).toUpperCase()}</span><span className="file-row-name"><b>{file.name}</b><small>{formatBytes(file.size)}</small></span><Check size={16} className="file-ok" /><button type="button" className="file-remove" aria-label={`Remove ${file.name}`} onClick={(event) => { event.stopPropagation(); setFiles((current) => current.filter((_, row) => row !== index)); }}><X size={15} /></button></div>)}</div>}
        {busy && <div className="progress-block"><div><span>{progress < 100 ? "Uploading original files" : "Queueing workflow"}</span><b>{progress}%</b></div><div className="progress-track"><span style={{ width: `${Math.max(progress, progress === 100 ? 100 : 4)}%` }} /></div></div>}
        {error && <InlineNotice tone="error">{error}</InlineNotice>}
        {result && <InlineNotice tone={result.queued ? "success" : "warning"}>{result.files.length} file(s) uploaded ({result.total_records} source rows). {result.queued ? `Workflow queued · ${result.job_id.slice(0, 8)}…` : "Upload is saved; queue the workflow from the overview when the worker is available."}</InlineNotice>}
        <div className="upload-actions"><span><ShieldCheck size={15} /> Source files remain unchanged</span><button className="button button-primary" disabled={busy || !files.length}><Upload size={16} />{busy ? "Processing upload…" : "Upload and harmonize"}<ArrowRight size={15} /></button></div>
      </form>
      <aside className="upload-aside"><div className="panel source-guide"><div className="guide-icon"><Globe2 size={18} /></div><span className="panel-kicker">WHAT HAPPENS NEXT</span><h3>One upload. A reviewable workflow.</h3><ol><li><span>1</span><div><b>Files are inspected</b><small>Format, columns, and row counts are recorded.</small></div></li><li><span>2</span><div><b>Records are harmonized</b><small>Known aliases map to the common land schema.</small></div></li><li><span>3</span><div><b>Quality checks run</b><small>Findings and source lineage remain attached.</small></div></li></ol><div className="guide-foot"><ShieldCheck size={14} /> Critical values are never silently rewritten.</div></div><div className="upload-tip"><div className="tip-icon"><Sparkles size={16} /></div><div><b>More context improves mapping</b><p>Use a clear source name. For Shapefiles, include the matching .shp, .shx, and .dbf files in one ZIP.</p></div></div></aside></div>
    </>
  );
}

function MetricCard({ label, value, detail, icon: Icon, tone }) {
  return <article className="metric-card"><div className={`metric-icon metric-${tone}`}><Icon size={17} strokeWidth={1.9} /></div><span className="metric-label">{label}</span><div className="metric-value">{Number(value).toLocaleString()}</div><div className="metric-detail">{detail}</div></article>;
}

function StatusBadge({ status }) {
  const normalized = (status || "unknown").toLowerCase();
  return <span className={`status-badge status-${normalized.replaceAll("_", "-")}`}><i />{normalized.replaceAll("_", " ")}</span>;
}

function InlineNotice({ tone, children }) {
  return <div className={`inline-notice notice-${tone}`}>{children}</div>;
}

function LoadingScreen({ label, compact = false }) {
  return <div className={`loading-screen ${compact ? "loading-compact" : ""}`}><LoaderCircle className="spin" size={20} /><span>{label}</span></div>;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
