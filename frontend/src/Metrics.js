import React, { useEffect, useState } from 'react';
import api from './api';
import jwtDecode from 'jwt-decode';
import AdminMenu from './AdminMenu';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  RadialBarChart,
  RadialBar,
  Legend,
} from 'recharts';
import MetricCard from './components/MetricCard';
import './Metrics.css';

function Metrics() {
  const [metricsData, setMetricsData] = useState(null);
  const [role, setRole] = useState('');
  const [loading, setLoading] = useState(true);
  const [interval] = useState('all');

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
        const resp = await api.get(`/metrics?interval=${interval}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        setMetricsData(resp.data);
      } catch (err) {
        console.error('Error fetching metrics:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchMetrics();
  }, []);

  if (loading) {
    return (
      <div className="metrics-container">
        <AdminMenu />
        Loading...
      </div>
    );
  }
  if (!metricsData) {
    return (
      <div className="metrics-container">
        <AdminMenu />
        Failed to load metrics
      </div>
    );
  }

  const highlight = [
    {
      title: 'Students',
      value: metricsData.total_student_profiles,
      data: metricsData.students_over_time || [metricsData.total_student_profiles],
    },
    {
      title: 'Jobs',
      value: metricsData.total_jobs_posted,
      data: metricsData.jobs_over_time || [metricsData.total_jobs_posted],
    },
    {
      title: 'Matches',
      value: metricsData.total_matches,
      data: metricsData.matches_over_time || [metricsData.total_matches],
    },
  ];

  if (role === 'admin') {
    highlight.push({
      title: 'Placement Rate',
      value: `${(metricsData.placement_rate * 100).toFixed(0)} %`,
      data: metricsData.placement_rate_over_time
        ? metricsData.placement_rate_over_time.map((n) => n * 100)
        : [metricsData.placement_rate * 100],
    });
    highlight.push({
      title: 'Rematch Rate',
      value: `${(metricsData.rematch_rate * 100).toFixed(0)} %`,
      data: metricsData.rematch_rate_over_time
        ? metricsData.rematch_rate_over_time.map((n) => n * 100)
        : [metricsData.rematch_rate * 100],
    });
  }

  const barData = [
    {
      name: 'Totals',
      Students: metricsData.total_student_profiles,
      Jobs: metricsData.total_jobs_posted,
      Matches: metricsData.total_matches,
    },
  ];

  const avgScore = metricsData.average_match_score
    ? Number(metricsData.average_match_score)
    : 0;

  const licenseData = Object.entries(
    metricsData.license_breakdown || {}
  ).map(([name, value]) => ({ name, value }));
  const colors = ['#00BFFF', '#32CD32', '#FF69B4', '#FFA500', '#9370DB'];

  return (
    <div className="metrics-container">
      <AdminMenu />
      <div className="metric-grid">
        {highlight.map((h) => (
          <MetricCard key={h.title} title={h.title} value={h.value} data={h.data} />
        ))}
      </div>
      {role === 'admin' && (
        <div className="avg-time"><strong>Average Time to Placement: {metricsData.avg_time_to_placement_days} days</strong></div>
      )}
      <div className="visual-section">
        {role === 'admin' ? (
          <ResponsiveContainer width={200} height={200}>
            <RadialBarChart
              innerRadius="80%"
              outerRadius="100%"
              data={[{ name: 'rate', value: metricsData.placement_rate * 100 }]}
            >
              <RadialBar dataKey="value" fill="#00BFFF" cornerRadius={10} />
              <text
                x="50%"
                y="50%"
                textAnchor="middle"
                dominantBaseline="middle"
                fill="#fff"
              >
                {(metricsData.placement_rate * 100).toFixed(0)}%
              </text>
            </RadialBarChart>
          </ResponsiveContainer>
        ) : (
          <div className="gauge-wrapper">
            <div
              className="gauge"
              style={{ background: `conic-gradient(#2ecc40 ${avgScore * 100}%, #555 ${avgScore * 100}% 100%)` }}
            >
              <span>{avgScore.toFixed(2)}</span>
            </div>
          </div>
        )}
        {role === 'admin' && (
          <ResponsiveContainer width={250} height={250}>
            <PieChart>
              <Pie dataKey="value" data={licenseData} outerRadius={80}>
                {licenseData.map((entry, index) => (
                  <Cell key={`c-${index}`} fill={colors[index % colors.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
      {role === 'admin' && (
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
            <LineChart data={[{ name: 'Latest', matches: metricsData.total_matches }]}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" stroke="#fff" />
              <YAxis stroke="#fff" />
              <Tooltip />
              <Line type="monotone" dataKey="matches" stroke="#FF4136" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default Metrics;
