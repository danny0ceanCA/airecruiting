import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import AdminMenu from './AdminMenu';
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

  // Tiles are conditionally rendered based on the user's role

  return (
    <div className="dashboard-container">
      <AdminMenu />
      <h2 className="dashboard-heading">Dashboard</h2>
      <div className="tile-grid">
        {role === 'admin' && (
          <>
            <Link to="/students" className="dashboard-tile">Student Profiles</Link>
            <Link to="/metrics" className="dashboard-tile">School Metrics</Link>
            <Link to="/career-info" className="dashboard-tile">Career Staff Information</Link>
            <Link to="/admin/pending" className="dashboard-tile">Pending Registrations</Link>
            <Link to="/admin/activity-log" className="dashboard-tile">Activity Log</Link>
          </>
        )}

        {role === 'career' && (
          <>
            <Link to="/students" className="dashboard-tile">Student Profiles</Link>
            <Link to="/metrics" className="dashboard-tile">School Metrics</Link>
            <Link to="/career-info" className="dashboard-tile">Career Staff Information</Link>
          </>
        )}

        {role === 'admin' || role === 'recruiter' ? (
          <Link to={role === 'admin' ? '/admin/jobs' : '/recruiter/jobs'}>
            <div className="dashboard-tile">Job Matching</div>
          </Link>
        ) : null}
        {role === 'applicant' && (
          <Link to="/applicant/profile" className="dashboard-tile">
            My Profile
          </Link>
        )}
      </div>
    </div>
  );
}

export default Dashboard;
