import React, { useEffect, useState } from 'react';
import api from './api';

function NursingNews() {
  const [feeds, setFeeds] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;
    api.get('/nursing-news')
      .then(resp => {
        if (mounted) {
          setFeeds(resp.data.feeds || []);
        }
      })
      .catch(() => {
        if (mounted) setError('Failed to load news feeds');
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="news-container">
      {error && <p className="error">{error}</p>}
      {feeds.map(feed => (
        <div key={feed.source} className="news-feed">
          <h3>{feed.source}</h3>
          <ul>
            {feed.articles && feed.articles.map((a, idx) => (
              <li key={idx}>
                <a href={a.link} target="_blank" rel="noopener noreferrer">
                  {a.title} »
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default NursingNews;
