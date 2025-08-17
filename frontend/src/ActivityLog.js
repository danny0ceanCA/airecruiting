import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import AdminMenu from './AdminMenu';
import api from './api';
import './ActivityLog.css';
import Skeleton from './components/Skeleton';

function ActivityLog() {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const token = localStorage.getItem('token');
  let role = '';
  if (token) {
    try {
      const dec = jwtDecode(token);
      role = dec.role;
    } catch {}
  }

  useEffect(() => {
    const fetchLog = async () => {
      setIsLoading(true);
      try {
        const resp = await api.get('/activity-log?limit=100', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setEntries(resp.data.entries || []);
      } catch (err) {
        console.error('Failed to load log:', err);
        setError(err.response?.data?.detail || 'Failed to load log');
      } finally {
        setIsLoading(false);
      }
    };
    if (token) fetchLog();
  }, [token]);

  if (role !== 'admin') {
    return <Navigate to="/dashboard" replace />;
  }

  const downloadCSV = () => {
    const header = 'timestamp,method,path,user';
    const rows = entries.map(e =>
      `${e.timestamp},${e.method},${e.path},${e.user}`
    );
    const csv = [header, ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', 'activity_log.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="activity-log-container">
      <AdminMenu />
      <h2>Activity Log</h2>
      {error && <p className="error">{error}</p>}
      <button className="download-btn" onClick={downloadCSV}>
        Download CSV
      </button>
      {isLoading ? (
        <div className="skeleton-container">
          {[...Array(5)].map((_, idx) => (
            <Skeleton key={idx} style={{ height: '20px', marginBottom: '10px' }} />
          ))}
        </div>
      ) : (
        <table className="log-table fade-in">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Method</th>
              <th>Path</th>
              <th>User</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, idx) => (
              <tr key={idx}>
                <td>{e.timestamp}</td>
                <td>{e.method}</td>
                <td>{e.path}</td>
                <td>{e.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default ActivityLog;
