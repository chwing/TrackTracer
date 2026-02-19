import React, { useState } from 'react';
import axios from 'axios';
import './App.css';

function Spinner() {
  return (
    <div className="spinner" aria-label="loading">
      <div></div>
      <div></div>
      <div></div>
      <div></div>
    </div>
  );
}

function App() {
  const [url, setUrl] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSearch = async () => {
    setError('');
    if (!url.trim()) {
      setError('Please paste a YouTube or SoundCloud link.');
      return;
    }

    setLoading(true);
    setData(null);
    try {
      const response = await axios.get(`http://localhost:8000/process?url=${encodeURIComponent(url)}`);
      setData(response.data);

      if (!response.data || !Array.isArray(response.data.tracks) || response.data.tracks.length === 0) {
        setError('No tracks found for the provided URL.');
      }
    } catch (err) {
      console.error(err);
      setError('Error fetching data. Check the link or backend.');
    }
    setLoading(false);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <div className="App-root">
      <header className="App-header">
        <div className="brand">
          <div className="logo" aria-hidden>🎧</div>
          <div>
            <h1 className="title">TrackTrace</h1>
            <p className="tagline">Extract tracklists from YouTube & SoundCloud links — quickly.</p>
          </div>
        </div>
      </header>

      <main className="App-main">
        <div className="card">
          <div className="card-left">
            <div className="search-row">
              <input
                className="url-input"
                type="text"
                placeholder="Paste YouTube or SoundCloud link"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={onKeyDown}
                aria-label="media url"
              />
              <button className="primary-btn" onClick={() => handleSearch()} disabled={loading}>
                {loading ? <Spinner /> : 'Find Tracks'}
              </button>
            </div>

            {error && <div className="notice error">{error}</div>}
            {!data && !loading && !error && <div className="hint">Try a link from YouTube or SoundCloud to get started.</div>}
          </div>

          <div className="card-right">
            {data ? (
              <section className="results">
                <div className="result-header">
                  <div className="result-header-content">
                    <div>
                      <h2 className="media-title">{data.title}</h2>
                      <div className="meta">Detected: <strong>{data.type}</strong></div>
                    </div>
                  </div>
                </div>

                <ul className="tracks">
                  {data.tracks.map((track, index) => (
                    <li key={index} className="track-item" style={{ animationDelay: `${index * 40}ms` }}>
                      <div className="time">{track.time}</div>
                      <div className="track-info">
                        <div className="track-title">{track.title}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : (
              <div style={{ padding: '48px 24px', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '400px', color: 'rgba(230,238,248,0.4)', fontFamily: 'Inter, sans-serif', fontSize: '14px' }}>
                No results yet
              </div>
            )}
          </div>
        </div>
      </main>

      <footer className="App-footer">
        <small>Made with ♥ — TrackTrace</small>
      </footer>
    </div>
  );
}

export default App;

