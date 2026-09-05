import { useState, useEffect } from "react";
import "./App.css";

const API_BASE = "http://localhost:8000";

function useCatalog() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/catalog`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load catalog (${res.status})`);
        return res.json();
      })
      .then((data) => setCatalog(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return { catalog, error, loading };
}

function ArtworkImage({ src, alt, className }) {
  const [errored, setErrored] = useState(false);
  return errored || !src ? (
    <div className={`${className} placeholder`}>{alt}</div>
  ) : (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => setErrored(true)}
      loading="lazy"
    />
  );
}

function EpisodeRow({ episode }) {
  const [lang, setLang] = useState(episode.languages[0]);
  return (
    <div className="episode-row">
      <ArtworkImage
        src={episode.artwork?.thumbnail}
        alt={episode.title}
        className="thumb"
      />
      <div className="episode-meta">
        <div className="episode-title">{episode.title}</div>
        <div className="lang-toggle">
          {episode.languages.map((l) => (
            <button
              key={l}
              className={l === lang ? "lang-pill active" : "lang-pill"}
              onClick={() => setLang(l)}
            >
              {l.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function ShowDetail({ show, onBack }) {
  return (
    <div className="show-detail">
      <button className="back-btn" onClick={onBack}>← Back</button>
      <h2>{show.title}</h2>
      <p className="synopsis">{show.synopsis}</p>

      {show.trailers?.length > 0 && (
        <section>
          <h3>Trailers</h3>
          {show.trailers.map((t) => (
            <EpisodeRow key={t.content_group} episode={t} />
          ))}
        </section>
      )}

      {show.seasons.map((season) => (
        <section key={season.number}>
          <h3>Season {season.number}</h3>
          {season.episodes.map((ep) => (
            <EpisodeRow key={ep.content_group} episode={ep} />
          ))}
        </section>
      ))}
    </div>
  );
}

function ShowCard({ show, onSelect }) {
  const posterUrl = show.seasons?.[0]?.episodes?.[0]?.artwork?.poster;
  return (
    <div className="show-card" onClick={() => onSelect(show)}>
      <ArtworkImage src={posterUrl} alt={show.title} className="poster" />
      <div className="show-card-title">{show.title}</div>
    </div>
  );
}

export default function App() {
  const { catalog, error, loading } = useCatalog();
  const [selectedShow, setSelectedShow] = useState(null);
  const [sectionFilter, setSectionFilter] = useState("all");
  const [query, setQuery] = useState("");

  if (loading) return <div className="state-message">Loading catalog…</div>;
  if (error) return <div className="state-message error">Couldn't load catalog — {error}. Retry by refreshing.</div>;
  if (!catalog || catalog.shows.length === 0) return <div className="state-message">No shows published yet.</div>;

  if (selectedShow) {
    return (
      <div className="app">
        <ShowDetail show={selectedShow} onBack={() => setSelectedShow(null)} />
      </div>
    );
  }

  const sections = ["all", ...new Set(catalog.shows.map((s) => s.section).filter(Boolean))];

  const filtered = catalog.shows.filter((s) => {
    const matchesSection = sectionFilter === "all" || s.section === sectionFilter;
    const matchesQuery = !query || s.title.toLowerCase().includes(query.toLowerCase());
    return matchesSection && matchesQuery;
  });

  return (
    <div className="app">
      <header className="header">
        <h1>Peblo TV</h1>
        <input
          className="search-box"
          placeholder="Search shows…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </header>

      <div className="filter-pills">
        {sections.map((sec) => (
          <button
            key={sec}
            className={sec === sectionFilter ? "pill active" : "pill"}
            onClick={() => setSectionFilter(sec)}
          >
            {sec}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="state-message">No results for "{query}"</div>
      ) : (
        <div className="show-grid">
          {filtered.map((show) => (
            <ShowCard key={show.slug} show={show} onSelect={setSelectedShow} />
          ))}
        </div>
      )}
    </div>
  );
}