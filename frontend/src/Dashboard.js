import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import './Dashboard.css';

function Dashboard() {
  const [role, setRole] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      try {
        const decoded = jwtDecode(token);
        setRole(decoded.role);
      } catch (err) {
        console.error('Failed to decode token', err);
      }
    }
  }, []);

  const tiles = [
    { label: 'Student Profiles', path: '/students', admin: false },
    { label: 'School Metrics', path: '/metrics', admin: false },
    { label: 'Pending Registrations', path: '/admin/pending', admin: true },
    { label: 'Job Matching', path: '/admin/jobs', admin: true },
  ];

  return (
    <div className="dashboard-container">
      <div className="tile-grid">
        {tiles
          .filter(tile => !tile.admin || role === 'admin')
          .map(tile => (
            <Link key={tile.path} to={tile.path} className="dashboard-tile">
              {tile.label}
            </Link>
          ))}
      </div>
    </div>
  );
}

export default Dashboard;
