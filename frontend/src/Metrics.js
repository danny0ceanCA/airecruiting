import React, { useEffect, useState } from 'react';
import axios from 'axios';
import jwtDecode from 'jwt-decode';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import './Metrics.css';

function Metrics() {
  const [data, setData] = useState(null);
  const [role, setRole] = useState('');
  const [loading, setLoading] = useState(true);
  const [interval, setInterval] = useState(30);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;
    try {
      const dec = jwtDecode(token);
      setRole(dec.role);
    } catch {
      return;
    }
    const fetchMetrics = async () => {
      try {
        const resp = await axios.get('/metrics', {
          headers: { Authorization: `Bearer ${token}` },
          params: { interval },
        });
        setData(resp.data);
      } catch (err) {
        console.error('Error fetching metrics:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchMetrics();
  }, [interval]);

  if (loading) {
    return <div className="metrics-container">Loading...</div>;
  }
  if (!data) {
    return <div className="metrics-container">Failed to load metrics</div>;
  }

  const highlight = [
    { label: 'Students', value: data.total_student_profiles },
    { label: 'Jobs', value: data.total_jobs_posted },
    { label: 'Matches', value: data.total_matches },
  ];

  const barData = [
    {
      name: 'Totals',
      Students: data.total_student_profiles,
      Jobs: data.total_jobs_posted,
      Matches: data.total_matches,
    },
  ];

  const avgScore = data.average_match_score ? Number(data.average_match_score) : 0;

  return (
    <div className="metrics-container">
      <div className="interval-controls">
        <h2>Metrics (Last {interval} Days)</h2>
        <select value={interval} onChange={(e) => setInterval(Number(e.target.value))}>
          <option value={7}>Last 7 Days</option>
          <option value={14}>Last 14 Days</option>
          <option value={30}>Last 30 Days</option>
          <option value={60}>Last 60 Days</option>
          <option value={90}>Last 90 Days</option>
          <option value={120}>Last 120 Days</option>
        </select>
      </div>
      <div className="highlight-grid">
        {highlight.map((h) => (
          <div key={h.label} className="highlight-card">
            <div className="value">{h.value}</div>
            <div className="label">{h.label}</div>
          </div>
        ))}
      </div>
      {role === 'admin' && (
        <>
          <div className="gauge-wrapper">
            <div
              className="gauge"
              style={{ background: `conic-gradient(#2ecc40 ${avgScore * 100}%, #555 ${avgScore * 100}% 100%)` }}
            >
              <span>{avgScore.toFixed(2)}</span>
            </div>
          </div>
          <div className="charts">
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={barData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" stroke="#fff" />
                <YAxis stroke="#fff" />
                <Tooltip />
                <Bar dataKey="Students" fill="#0074D9" />
                <Bar dataKey="Jobs" fill="#2ECC40" />
                <Bar dataKey="Matches" fill="#FF851B" />
              </BarChart>
            </ResponsiveContainer>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={[{ name: 'Latest', matches: data.total_matches }]}> 
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" stroke="#fff" />
                <YAxis stroke="#fff" />
                <Tooltip />
                <Line type="monotone" dataKey="matches" stroke="#FF4136" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}

export default Metrics;
