import { useCallback, useEffect, useState } from "react";
import {
  BookOpen, Check, FileText, LoaderCircle, Search, ShieldCheck,
  Sparkles, TriangleAlert, Upload,
} from "lucide-react";
import { apiRequest } from "../services/api.js";

const ACCEPTED_TYPES = ".md,.txt,.json";

export default function KnowledgePage() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [ruleKey, setRuleKey] = useState("");
  const [version, setVersion] = useState("1");
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResult, setSearchResult] = useState(null);
  const [notice, setNotice] = useState(null);

  const loadDocuments = useCallback(async () => {
    try {
      const result = await apiRequest("/api/v1/knowledge/documents");
      setDocuments(result);
    } catch (error) {
      setNotice({ tone: "error", text: `Could not load indexed documents: ${error.message}` });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  const chooseFile = (nextFile) => {
    if (!nextFile) return;
    if (nextFile.size > 1_000_000) {
      setNotice({ tone: "error", text: "Document must be 1 MB or smaller." });
      return;
    }
    setFile(nextFile);
    if (!title) setTitle(nextFile.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
    if (!ruleKey) setRuleKey(nextFile.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, ""));
    setNotice(null);
  };

  const upload = async (event) => {
    event.preventDefault();
    if (!file) {
      setNotice({ tone: "error", text: "Choose a Markdown, TXT, or JSON file first." });
      return;
    }
    const uploadForm = event.currentTarget;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title.trim());
    formData.append("rule_key", ruleKey.trim());
    formData.append("version", version.trim() || "1");
    setUploading(true);
    setNotice(null);
    try {
      const indexed = await apiRequest("/api/v1/knowledge/documents", { method: "POST", body: formData });
      setNotice({ tone: "success", text: `Indexed ${indexed.chunks} rule chunk${indexed.chunks === 1 ? "" : "s"} using ${indexed.embedding_provider} embeddings.` });
      setFile(null);
      setTitle("");
      setRuleKey("");
      setVersion("1");
      uploadForm.reset();
      await loadDocuments();
    } catch (error) {
      setNotice({ tone: "error", text: error.message });
    } finally {
      setUploading(false);
    }
  };

  const search = async (event) => {
    event.preventDefault();
    setSearching(true);
    setNotice(null);
    try {
      const result = await apiRequest("/api/v1/knowledge/search", {
        method: "POST",
        body: JSON.stringify({ query: query.trim(), limit: 5 }),
      });
      setSearchResult(result);
    } catch (error) {
      setNotice({ tone: "error", text: error.message });
    } finally {
      setSearching(false);
    }
  };

  return (
    <>
      <div className="page-heading">
        <div><div className="eyebrow"><span className="eyebrow-dot" /> LAND-DATA STANDARDS</div><h1>Knowledge base</h1><p>Index workspace rules and inspect the guidance retrieved for a search.</p></div>
      </div>
      {notice && <div className={`inline-notice notice-${notice.tone}`} role="status">{notice.tone === "success" ? <Check size={15} /> : <TriangleAlert size={15} />}{notice.text}<button className="notice-action" onClick={() => setNotice(null)}>Dismiss</button></div>}

      <div className="knowledge-grid">
        <section className="panel knowledge-panel">
          <div className="report-panel-heading"><div><span className="panel-kicker">RULE DOCUMENTS</span><h2>Add a source</h2></div><span className="knowledge-icon"><Upload size={16} /></span></div>
          <p className="knowledge-intro">Add project dictionaries or validation guidance. Documents are private to this workspace and remain linked to the retrieved rule chunks.</p>
          <form className="knowledge-form" onSubmit={upload}>
            <label>Document title<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={500} required placeholder="Example: Parcel identifier policy" /></label>
            <div className="knowledge-form-row">
              <label>Rule key<input value={ruleKey} onChange={(event) => setRuleKey(event.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, "-"))} maxLength={160} pattern="[a-z0-9][a-z0-9._-]{0,159}" required placeholder="parcel-id-policy" /></label>
              <label>Version<input value={version} onChange={(event) => setVersion(event.target.value)} maxLength={80} required placeholder="1" /></label>
            </div>
            <label className="knowledge-file-input">Choose document<input type="file" accept={ACCEPTED_TYPES} onChange={(event) => chooseFile(event.target.files?.[0])} /><span><FileText size={16} />{file ? `${file.name} · ${formatBytes(file.size)}` : "Markdown, TXT, or JSON · max 1 MB"}</span></label>
            <button className="button button-primary" type="submit" disabled={uploading || !file}>{uploading ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}{uploading ? "Indexing…" : "Index document"}</button>
          </form>
          <div className="knowledge-privacy"><ShieldCheck size={15} />Workspace-scoped · Original file preserved · Duplicate versions rejected</div>
        </section>

        <section className="panel knowledge-panel">
          <div className="report-panel-heading"><div><span className="panel-kicker">PGVECTOR RETRIEVAL</span><h2>Search rules</h2></div><span className="knowledge-icon knowledge-spark"><Sparkles size={16} /></span></div>
          <p className="knowledge-intro">Search is a review aid. Retrieved guidance informs QA but never changes a land-record value by itself.</p>
          <form className="knowledge-search" onSubmit={search}>
            <label className="sr-only" htmlFor="rule-search">Search indexed rules</label>
            <Search size={16} />
            <input id="rule-search" value={query} onChange={(event) => setQuery(event.target.value)} minLength={3} maxLength={2000} required placeholder="e.g. What checks apply to parcel area?" />
            <button className="button button-primary" type="submit" disabled={searching || query.trim().length < 3}>{searching ? <LoaderCircle className="spin" size={15} /> : "Search"}</button>
          </form>
          {searchResult ? <div className="knowledge-results">
            <div className="knowledge-result-meta">{searchResult.results.length} result{searchResult.results.length === 1 ? "" : "s"} · {searchResult.provider} embeddings</div>
            {searchResult.results.length ? searchResult.results.map((result) => <article className="knowledge-result" key={result.id}><div><b>{result.title}</b><span>{result.document_rule_key} · v{result.version} · {Math.round(result.similarity * 100)}% similarity</span></div><p>{result.content}</p><small>{result.source_reference || result.rule_key}</small></article>) : <div className="subtle-empty">No indexed rules matched. Add a document or try a different phrase.</div>}
          </div> : <div className="knowledge-search-empty"><BookOpen size={21} /><span>Search results will include the matching text and source reference.</span></div>}
        </section>
      </div>

      <section className="panel knowledge-documents">
        <div className="report-panel-heading"><div><span className="panel-kicker">WORKSPACE INDEX</span><h2>Indexed documents</h2></div><span>{loading ? "Loading…" : `${documents.length} document${documents.length === 1 ? "" : "s"}`}</span></div>
        {loading ? <div className="report-empty"><LoaderCircle className="spin" size={18} />Loading indexed documents…</div> : documents.length ? <div className="knowledge-document-list">{documents.map((document) => <article className="knowledge-document" key={document.document_id}><span className="knowledge-document-icon"><FileText size={16} /></span><div><b>{document.title}</b><small>{document.filename} · {document.rule_key} · v{document.version}</small></div><span className="knowledge-chunks">{document.chunks} chunks</span><span className="knowledge-provider">{document.embedding_provider}</span></article>)}</div> : <div className="subtle-empty knowledge-empty">No documents indexed yet. Add a synthetic or project-authored rule document above.</div>}
      </section>
    </>
  );
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}
