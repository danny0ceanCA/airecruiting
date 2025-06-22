import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from './api';
import './AdminPending.css';

function AdminPending() {
  const [pendingUsers, setPendingUsers] = useState([]);
  // Temporary toast message shown when a user is approved
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');

  const fetchPending = async () => {
    setError('');
    try {
      const resp = await api.get('/pending-users', {
        headers: { Authorization: `Bearer ${token}` },
      });
      setPendingUsers(resp.data);
    } catch (err) {
      console.error('Error fetching pending users:', err);
      setError(err.response?.data?.detail || 'Failed to fetch');
    }
  };

  useEffect(() => {
    if (token) {
      fetchPending();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const approve = async (email) => {
    setToast('');
    setError('');
    try {
      await api.post(
        '/approve',
        { email },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setToast('User approved!');
      // refresh list
      fetchPending();
      setTimeout(() => setToast(''), 3000);
    } catch (err) {
      console.error('Error approving user:', err);
      setError(err.response?.data?.detail || 'Approval failed');
    }
  };

  const reject = async (email) => {
    setToast('');
    setError('');
    try {
      await api.post(
        '/reject',
        { email },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setToast('User rejected!');
      fetchPending();
      setTimeout(() => setToast(''), 3000);
    } catch (err) {
      console.error('Error rejecting user:', err);
      setError(err.response?.data?.detail || 'Rejection failed');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  if (!token) {
    return <p className="pending-container">Login required.</p>;
  }

  return (
    <div className="pending-container">
      <div className="admin-menu">
        <button
          className="menu-button"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Admin Menu
        </button>
        {menuOpen && (
          <div className="dropdown-menu">
            <Link to="/dashboard">Dashboard</Link>
            <Link to="/admin/jobs">Job Matching</Link>
            <button onClick={handleLogout}>Logout</button>
          </div>
        )}
      </div>
      <h2>Pending Registrations</h2>
      {toast && <div className="toast">{toast}</div>}
      {error && <p className="error">{error}</p>}
      <table className="pending-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>School</th>
            <th>Role</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {pendingUsers.map((user) => (
            <tr key={user.email}>
              <td>{user.email}</td>
              <td>{user.school}</td>
              <td>{user.role}</td>
              <td>
                <button className="approve-button" onClick={() => approve(user.email)}>Approve</button>
                <button className="reject-button" onClick={() => reject(user.email)}>Reject</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default AdminPending;
