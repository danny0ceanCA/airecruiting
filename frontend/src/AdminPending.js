import React, { useEffect, useState } from 'react';
import AdminMenu from './AdminMenu';
import api from './api';
import './AdminPending.css';

function AdminPending() {
  const [pendingUsers, setPendingUsers] = useState([]);
  // Temporary toast message shown when a user is approved
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [selectedRoles, setSelectedRoles] = useState({});

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

  const handleApprove = async (email) => {
    setToast('');
    setError('');
    try {
      const role = selectedRoles[email] || 'career';
      await api.post(
        '/approve',
        { email, role },
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

  const handleReject = async (email) => {
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


  if (!token) {
    return <p className="pending-container">Login required.</p>;
  }

  return (
    <div className="pending-container">
      <AdminMenu />
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
                <select
                  value={selectedRoles[user.email] || 'career'}
                  onChange={(e) =>
                    setSelectedRoles((prev) => ({ ...prev, [user.email]: e.target.value }))
                  }
                  style={{
                    padding: '4px 8px',
                    marginRight: '10px',
                    borderRadius: '4px',
                  }}
                >
                  <option value="career">Career Service Staff</option>
                  <option value="recruiter">Recruiter</option>
                </select>
                <button className="approve-button" onClick={() => handleApprove(user.email)}>Approve</button>
                <button className="reject-button" onClick={() => handleReject(user.email)}>Reject</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default AdminPending;
