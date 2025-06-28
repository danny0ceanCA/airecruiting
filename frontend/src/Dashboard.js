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

  // Tiles are conditionally rendered based on the user's role

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
        {role === 'admin' && (
          <>
            <Link to="/students" className="dashboard-tile">Student Profiles</Link>
            <Link to="/metrics" className="dashboard-tile">School Metrics</Link>
            <Link to="/admin/pending" className="dashboard-tile">Pending Registrations</Link>
            <Link to="/admin/jobs" className="dashboard-tile">Job Matching</Link>
          </>
        )}

        {role === 'career' && (
          <>
            <Link to="/students" className="dashboard-tile">Student Profiles</Link>
            <Link to="/metrics" className="dashboard-tile">School Metrics</Link>
          </>
        )}

        {role === 'recruiter' && (
          <>
            <Link to="/admin/jobs" className="dashboard-tile">Job Matching</Link>
          </>
        )}
      </div>
    </div>
  );
}

export default Dashboard;
