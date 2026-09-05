import { useState, useEffect } from "react";
import "./App.css";

const API_BASE = "http://localhost:8000";
const SECTIONS = ["featured", "series", "minisodes", "songs"];
const LANGUAGES = ["en", "hi"];
const ARTWORK_TYPES = [
  { type: "poster", label: "Poster", spec: "600×900 · 2:3 · max 200 KB" },
  { type: "banner", label: "Banner", spec: "1280×720 · 16:9 · max 200 KB" },
  { type: "thumbnail", label: "Thumbnail", spec: "640×360 · 16:9 · max 200 KB" },
];

// --- role switcher (dev shortcut, mirrors the header-based auth on the API) ---
function useRole() {
  const [role, setRole] = useState("editor");
  return { role, setRole };
}

async function apiFetch(path, role, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: { ...(opts.headers || {}), "X-Role": role },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

function RoleSwitcher({ role, setRole }) {
  return (
    <div className="role-switcher">
      <span>Acting as:</span>
      {["editor", "admin"].map((r) => (
        <button
          key={r}
          className={r === role ? "role-pill active" : "role-pill"}
          onClick={() => setRole(r)}
        >
          {r}
        </button>
      ))}
    </div>
  );
}

function Nav({ tab, setTab }) {
  return (
    <nav className="nav">
      <div className="nav-title">Peblo CMS</div>
      <div className="nav-tabs">
        {["episodes", "publish"].map((t) => (
          <button
            key={t}
            className={tab === t ? "nav-tab active" : "nav-tab"}
            onClick={() => setTab(t)}
          >
            {t === "episodes" ? "Episodes" : "Publish"}
          </button>
        ))}
      </div>
    </nav>
  );
}

function EpisodeList({ role, onEdit }) {
  const [episodes, setEpisodes] = useState(null);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");

  const load = () => {
    setError(null);
    apiFetch("/admin/episodes", role)
      .then(setEpisodes)
      .catch((e) => setError(e.message));
  };

  useEffect(load, [role]);

  if (error) return <div className="state-message error">Couldn't load episodes — {error}. <button onClick={load}>Retry</button></div>;
  if (!episodes) return <div className="state-message">Loading…</div>;

  const filtered = episodes.filter((e) => statusFilter === "all" || e.status === statusFilter);

  return (
    <div>
      <div className="toolbar">
        <div className="filter-pills">
          {["all", "draft", "published"].map((s) => (
            <button
              key={s}
              className={s === statusFilter ? "pill active" : "pill"}
              onClick={() => setStatusFilter(s)}
            >
              {s}
            </button>
          ))}
        </div>
        <button className="primary-btn" onClick={() => onEdit(null)}>+ New episode</button>
      </div>

      {filtered.length === 0 ? (
        <div className="state-message">No episodes match your filters.</div>
      ) : (
        <table className="episode-table">
          <thead>
            <tr>
              <th>Title</th><th>Content group</th><th>Language</th><th>Status</th><th>Duration</th><th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((ep) => (
              <tr key={ep.id}>
                <td>{ep.title}</td>
                <td className="mono">{ep.content_group}</td>
                <td>{ep.language.toUpperCase()}</td>
                <td><span className={`status-badge ${ep.status}`}>{ep.status}</span></td>
                <td>{ep.duration_seconds ? `${ep.duration_seconds}s` : "—"}</td>
                <td><button className="link-btn" onClick={() => onEdit(ep)}>Edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ArtworkSlot({ episodeId, type, label, spec, role, onUploaded }) {
  const [status, setStatus] = useState("idle"); // idle | uploading | success | error
  const [message, setMessage] = useState("");
  const [previewUrl, setPreviewUrl] = useState(null);

  const handleFile = async (file) => {
    if (!episodeId) {
      setStatus("error");
      setMessage("Save the episode first before uploading artwork.");
      return;
    }
    setStatus("uploading");
    setPreviewUrl(URL.createObjectURL(file));

    const form = new FormData();
    form.append("type", type);
    form.append("file", file);

    try {
      const result = await apiFetch(`/admin/episodes/${episodeId}/artwork`, role, {
        method: "POST",
        body: form,
      });
      setStatus("success");
      setMessage(`${result.width}×${result.height}`);
      onUploaded?.();
    } catch (e) {
      setStatus("error");
      setMessage(e.message);
    }
  };

  return (
    <div className={`artwork-slot ${status}`}>
      <div className="artwork-label">{label}</div>
      <div className="artwork-spec">{spec}</div>
      <label className="artwork-dropzone">
        {previewUrl && status !== "error" ? (
          <img src={previewUrl} alt={label} className="artwork-preview" />
        ) : (
          <span>Click to upload</span>
        )}
        <input
          type="file"
          accept="image/jpeg,image/png"
          onChange={(e) => e.target.files[0] && handleFile(e.target.files[0])}
          hidden
        />
      </label>
      {status === "success" && <div className="artwork-status success">✓ {message}</div>}
      {status === "error" && <div className="artwork-status error">{message}</div>}
      {status === "uploading" && <div className="artwork-status">Uploading…</div>}
    </div>
  );
}

function EpisodeForm({ role, episode, onDone }) {
  const [title, setTitle] = useState(episode?.title || "");
  const [contentGroup, setContentGroup] = useState(episode?.content_group || "");
  const [language, setLanguage] = useState(episode?.language || "en");
  const [duration, setDuration] = useState(episode?.duration_seconds || "");
  const [status, setStatus] = useState(episode?.status || "draft");
  const [saveError, setSaveError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [episodeId, setEpisodeId] = useState(episode?.id || null);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // Minimal CMS: this demo build only supports updating status on existing episodes,
      // since full create/update CRUD for shows/seasons wasn't built out given time constraints.
      // New episodes must currently be created via the seed data or a direct API call.
      if (!episodeId) {
        setSaveError("Creating brand-new episodes from the CMS isn't wired up yet — this form currently supports editing status/metadata on existing episodes only (see README).");
        setSaving(false);
        return;
      }
      await apiFetch(`/admin/episodes/${episodeId}/status?status=${status}`, role, {
        method: "PATCH",
      });
      onDone();
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="episode-form">
      <button className="back-btn" onClick={onDone}>← Back to list</button>
      <h2>{episode ? "Edit episode" : "New episode"}</h2>

      <div className="form-grid">
        <label>Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!!episode} />
        </label>
        <label>Content group
          <input value={contentGroup} onChange={(e) => setContentGroup(e.target.value)} disabled={!!episode} />
        </label>
        <label>Language
          <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={!!episode}>
            {LANGUAGES.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
          </select>
        </label>
        <label>Duration (seconds)
          <input value={duration} disabled />
        </label>
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
          </select>
        </label>
      </div>

      <h3>Artwork uploads</h3>
      <div className="artwork-grid">
        {ARTWORK_TYPES.map((a) => (
          <ArtworkSlot
            key={a.type + refreshKey}
            episodeId={episodeId}
            type={a.type}
            label={a.label}
            spec={a.spec}
            role={role}
            onUploaded={() => setRefreshKey((k) => k + 1)}
          />
        ))}
      </div>

      {saveError && <div className="state-message error">{saveError}</div>}

      <div className="form-actions">
        <button className="secondary-btn" onClick={onDone}>Cancel</button>
        <button className="primary-btn" onClick={handleSave} disabled={saving}>
          {saving ? "Saving…" : "Save episode"}
        </button>
      </div>
    </div>
  );
}

function PublishPage({ role }) {
  const [report, setReport] = useState(null);
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState(null);

  const load = () => {
    setError(null);
    Promise.all([
      apiFetch("/admin/validation-report", role),
      apiFetch("/admin/catalog/publish-runs", role),
    ])
      .then(([r, ru]) => {
        setReport(r);
        setRuns(ru);
      })
      .catch((e) => setError(e.message));
  };

  useEffect(load, [role]);

  const handlePublish = async () => {
    setPublishing(true);
    setPublishResult(null);
    try {
      const result = await apiFetch("/admin/catalog/publish", role, { method: "POST" });
      setPublishResult({ ok: true, ...result });
      load();
    } catch (e) {
      setPublishResult({ ok: false, message: e.message });
    } finally {
      setPublishing(false);
    }
  };

  if (error) return <div className="state-message error">Couldn't load publish data — {error}</div>;
  if (!report || !runs) return <div className="state-message">Loading…</div>;

  const blockingCount = report.missing_artwork.length + report.missing_duration.length;
  const isAdmin = role === "admin";

  return (
    <div>
      <div className="publish-header">
        <h2>Publish catalogue</h2>
        <button
          className="primary-btn"
          disabled={blockingCount > 0 || publishing || !isAdmin}
          title={!isAdmin ? "Admins only" : blockingCount > 0 ? "Resolve blocking issues first" : ""}
          onClick={handlePublish}
        >
          {publishing ? "Publishing…" : "Publish catalogue"}
        </button>
      </div>

      {!isAdmin && (
        <div className="state-message error">Admins only — switch role to "admin" above to publish.</div>
      )}

      {publishResult && (
        publishResult.ok ? (
          <div className="state-message success">
            Published {publishResult.shows} shows, {publishResult.episodes} episodes.
          </div>
        ) : (
          <div className="state-message error">{publishResult.message}</div>
        )
      )}

      <h3>Validation report</h3>
      {blockingCount === 0 ? (
        <div className="state-message success">✓ No blocking issues — catalogue is ready to publish.</div>
      ) : (
        <div className="validation-list">
          {report.missing_artwork.map((issue) => (
            <div key={issue.episode_id} className="validation-issue">
              <strong>Missing artwork</strong> — {issue.title}: needs {issue.missing.join(", ")}
            </div>
          ))}
          {report.missing_duration.map((issue) => (
            <div key={issue.episode_id} className="validation-issue">
              <strong>Missing duration</strong> — {issue.title}
            </div>
          ))}
        </div>
      )}

      <h3>Publish run history</h3>
      <div className="run-history">
        {runs.length === 0 ? (
          <div className="state-message">No publishes yet.</div>
        ) : (
          runs.map((run) => (
            <div key={run.id} className={`run-entry ${run.status}`}>
              <span className={`status-badge ${run.status}`}>{run.status}</span>
              <span>{run.triggered_by}</span>
              <span>{run.show_count ?? 0} shows · {run.episode_count ?? 0} episodes</span>
              <span className="run-time">{new Date(run.started_at).toLocaleString()}</span>
              {run.error_detail && <span className="run-error">{run.error_detail}</span>}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function App() {
  const { role, setRole } = useRole();
  const [tab, setTab] = useState("episodes");
  const [editingEpisode, setEditingEpisode] = useState(undefined); // undefined = list view

  return (
    <div className="cms-app">
      <Nav tab={tab} setTab={setTab} />
      <div className="cms-body">
        <RoleSwitcher role={role} setRole={setRole} />

        {tab === "episodes" && editingEpisode === undefined && (
          <EpisodeList role={role} onEdit={setEditingEpisode} />
        )}
        {tab === "episodes" && editingEpisode !== undefined && (
          <EpisodeForm
            role={role}
            episode={editingEpisode}
            onDone={() => setEditingEpisode(undefined)}
          />
        )}
        {tab === "publish" && <PublishPage role={role} />}
      </div>
    </div>
  );
}