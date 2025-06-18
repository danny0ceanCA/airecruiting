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
        });
        setData(resp.data);
      } catch (err) {
        console.error('Error fetching metrics:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchMetrics();
  }, []);

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
