import React, { useEffect, useState } from 'react';
import axios from 'axios';
import './AdminPending.css';

function AdminPending() {
  const [pendingUsers, setPendingUsers] = useState([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const token = localStorage.getItem('token');

  const fetchPending = async () => {
    setError('');
    try {
      const resp = await axios.get('http://localhost:8000/pending-users', {
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
    setMessage('');
    setError('');
    try {
      await axios.post(
        'http://localhost:8000/approve',
        { email },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMessage(`${email} approved`);
      // refresh list
      fetchPending();
    } catch (err) {
      console.error('Error approving user:', err);
      setError(err.response?.data?.detail || 'Approval failed');
    }
  };

  if (!token) {
    return <p className="pending-container">Login required.</p>;
  }

  return (
    <div className="pending-container">
      <h2>Pending Registrations</h2>
      {message && <p className="message">{message}</p>}
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
                <button onClick={() => approve(user.email)}>Approve</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default AdminPending;
