import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import './Dashboard.css';

function Dashboard() {
  const [role, setRole] = useState('');
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

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
      <div style={{ position: 'absolute', top: '20px', right: '30px' }}>
        <button
          style={{
            padding: '6px 14px',
            border: 'none',
            borderRadius: '6px',
            backgroundColor: '#fff',
            color: '#002244',
            fontWeight: 'bold',
            cursor: 'pointer',
            boxShadow: '0 2px 6px rgba(0,0,0,0.2)'
          }}
          onClick={handleLogout}
        >
          Logout
        </button>
      </div>
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
