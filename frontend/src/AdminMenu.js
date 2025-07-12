import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import jwt_decode from 'jwt-decode';
import './AdminMenu.css';

function AdminMenu({ children }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');
  const decoded = token ? jwt_decode(token) : {};
  const userRole = decoded?.role;

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="admin-menu">
      <button className="menu-button" onClick={() => setMenuOpen((o) => !o)}>
        Menu
      </button>
      {menuOpen && (
        <div className="dropdown-menu">
          <Link to="/dashboard">Dashboard</Link>
          {userRole === 'admin' && (
            <>
              <Link to="/admin/pending">Pending Approvals</Link>
              <Link to="/students">Student Profiles</Link>
              <Link to="/admin/jobs">Job Matching</Link>
              <Link to="/admin/activity-log">Activity Log</Link>
              <Link to="/admin/users">Manage Users</Link>
            </>
          )}
          {userRole === 'recruiter' && (
            <Link to="/recruiter/jobs">Job Matching</Link>
          )}
          {userRole === 'applicant' && (
            <Link to="/applicant/profile">Applicant Profile</Link>
          )}
          {userRole === 'career' && (
            <>
              <Link to="/students">Student Profiles</Link>
            </>
          )}
          {children}
          <button onClick={handleLogout}>Logout</button>
        </div>
      )}
    </div>
  );
}

export default AdminMenu;
