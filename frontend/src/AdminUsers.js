import React, { useEffect, useState } from 'react';
import AdminMenu from './AdminMenu';
import api from './api';
import './AdminUsers.css';

function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [message, setMessage] = useState('');
  const token = localStorage.getItem('token');

  const fetchUsers = async () => {
    try {
      const resp = await api.get('/admin/users', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setUsers(resp.data.users || []);
    } catch (err) {
      console.error('Failed to fetch users', err);
    }
  };

  useEffect(() => {
    if (token) fetchUsers();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (email, field, value) => {
    setUsers((prev) =>
      prev.map((u) => (u.email === email ? { ...u, [field]: value } : u))
    );
  };

  const handleSave = async (user) => {
    setMessage('');
    try {
      await api.put(
        `/admin/users/${user.email}`,
        {
          role: user.role,
          school_code: user.institutional_code,
          active: user.active
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMessage('Saved!');
      setTimeout(() => setMessage(''), 2000);
    } catch (err) {
      console.error('Save failed', err);
    }
  };

  return (
    <div className="users-container">
      <AdminMenu />
      <h2>Manage Users</h2>
      {message && <div className="toast">{message}</div>}
      <table className="users-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>First Name</th>
            <th>Last Name</th>
            <th>School</th>
            <th>Role</th>
            <th>Active</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.email}>
              <td>{u.email}</td>
              <td>{u.first_name}</td>
              <td>{u.last_name}</td>
              <td>
                <input
                  type="text"
                  value={u.institutional_code || ''}
                  onChange={(e) =>
                    handleChange(u.email, 'institutional_code', e.target.value)
                  }
                />
              </td>
              <td>
                <select
                  value={u.role}
                  onChange={(e) => handleChange(u.email, 'role', e.target.value)}
                >
                  <option value="admin">Admin</option>
                  <option value="career">Career</option>
                  <option value="recruiter">Recruiter</option>
                  <option value="applicant">Applicant</option>
                </select>
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={u.active !== false}
                  onChange={(e) =>
                    handleChange(u.email, 'active', e.target.checked)
                  }
                />
              </td>
              <td>
                <button onClick={() => handleSave(u)}>Save</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default AdminUsers;
