import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FaUsers,
  FaChartLine,
  FaUserTie,
  FaCheckCircle,
  FaListUl,
  FaUserCog,
  FaBriefcase,
} from 'react-icons/fa';
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
            <Link to="/students" className="dashboard-tile">
              <FaUsers className="tile-icon" />
              <span>Student Profiles</span>
            </Link>
            <Link to="/metrics" className="dashboard-tile">
              <FaChartLine className="tile-icon" />
              <span>School Metrics</span>
            </Link>
            <Link to="/career-info" className="dashboard-tile">
              <FaUserTie className="tile-icon" />
              <span>Career Staff Information</span>
            </Link>
            <Link to="/admin/pending" className="dashboard-tile">
              <FaCheckCircle className="tile-icon" />
              <span>Pending Registrations</span>
            </Link>
            <Link to="/admin/activity-log" className="dashboard-tile">
              <FaListUl className="tile-icon" />
              <span>Activity Log</span>
            </Link>
            <Link to="/admin/users" className="dashboard-tile">
              <FaUserCog className="tile-icon" />
              <span>Manage Users</span>
            </Link>
          </>
        )}

        {role === 'career' && (
          <>
            <Link to="/students" className="dashboard-tile">
              <FaUsers className="tile-icon" />
              <span>Student Profiles</span>
            </Link>
            <Link to="/metrics" className="dashboard-tile">
              <FaChartLine className="tile-icon" />
              <span>School Metrics</span>
            </Link>
            <Link to="/career-info" className="dashboard-tile">
              <FaUserTie className="tile-icon" />
              <span>Career Staff Information</span>
            </Link>
          </>
        )}

        {role === 'applicant' && (
          <Link to="/applicant/profile" className="dashboard-tile">
            <FaUserTie className="tile-icon" />
            <span>Applicant Profile</span>
          </Link>
        )}

        {role === 'admin' || role === 'recruiter' ? (
          <Link to={role === 'admin' ? '/admin/jobs' : '/recruiter/jobs'} className="dashboard-tile">
            <FaBriefcase className="tile-icon" />
            <span>Job Matching</span>
          </Link>
        ) : null}
      </div>
    </div>
  );
}

export default Dashboard;
