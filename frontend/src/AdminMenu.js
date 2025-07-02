import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import jwt_decode from 'jwt-decode';

function AdminMenu({ children }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');
  const decoded = token ? jwt_decode(token) : {};
  const userRole = decoded?.role;
  const careerLabel = process.env.REACT_APP_CAREER_BTN_TEXT || "Career Staff";

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="admin-menu">
      {userRole === "career" && (
        <Link className="career-button" to="/career-info">
          {careerLabel}
        </Link>
      )}
      <button className="menu-button" onClick={() => setMenuOpen((o) => !o)}>
        Menu
      </button>
      {menuOpen && (
        <div className="dropdown-menu">
          {userRole === 'admin' && (
            <>
              <Link to="/dashboard">Dashboard</Link>
              <Link to="/admin/pending">Pending Approvals</Link>
              <Link to="/students">Student Profiles</Link>
              <Link to="/admin/jobs">Job Matching</Link>
            </>
          )}
          {userRole === 'recruiter' && (
            <Link to="/recruiter/jobs">Job Matching</Link>
          )}
          {userRole === 'career' && <Link to="/students">Student Profiles</Link>}
          {children}
          <button onClick={handleLogout}>Logout</button>
        </div>
      )}
    </div>
  );
}

export default AdminMenu;
