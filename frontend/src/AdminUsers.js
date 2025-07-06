import React, { useEffect, useState } from 'react';
import AdminMenu from './AdminMenu';
import api from './api';
import './AdminUsers.css';

function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [codes, setCodes] = useState([]);
  const [message, setMessage] = useState('');
  const [newCode, setNewCode] = useState('');
  const [newLabel, setNewLabel] = useState('');
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

  const fetchCodes = async () => {
    try {
      const resp = await api.get('/school-codes');
      setCodes(resp.data.codes || []);
    } catch (err) {
      console.error('Failed to fetch school codes', err);
    }
  };

  useEffect(() => {
    if (token) fetchUsers();
    fetchCodes();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (email, field, value) => {
    setUsers((prev) =>
      prev.map((u) => (u.email === email ? { ...u, [field]: value } : u))
    );
  };

  const labelToCode = (label) => {
    const found = codes.find((c) => c.label === label || c.code === label);
    return found ? found.code : label;
  };

  const handleSave = async (user) => {
    setMessage('');
    try {
      await api.put(
        `/admin/users/${user.email}`,
        {
          role: user.role,
          school_code: labelToCode(user.institutional_code),
          active: user.active
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMessage('Saved!');
      fetchUsers();
      setTimeout(() => setMessage(''), 2000);
    } catch (err) {
      console.error('Save failed', err);
    }
  };

  const handleAddCode = async () => {
    try {
      await api.post(
        '/admin/school-codes',
        { code: newCode, label: newLabel },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setNewCode('');
      setNewLabel('');
      fetchCodes();
    } catch (err) {
      console.error('Failed to add code', err);
    }
  };

  const handleDelete = async (email) => {
    if (!window.confirm(`Delete user ${email}?`)) return;
    try {
      await api.delete(`/admin/users/${email}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      fetchUsers();
    } catch (err) {
      console.error('Delete failed', err);
    }
  };

  return (
    <div className="users-container">
      <AdminMenu />
      <div className="users-header">
        <h2>Manage Users</h2>
        <button className="refresh-btn" onClick={fetchUsers}>Refresh</button>
      </div>
      <div className="add-code-form">
        <input
          type="text"
          placeholder="Code"
          value={newCode}
          onChange={(e) => setNewCode(e.target.value)}
        />
        <input
          type="text"
          placeholder="Label"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
        />
        <button onClick={handleAddCode}>Add Code</button>
      </div>
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
                <select
                  value={labelToCode(u.institutional_code || '')}
                  onChange={(e) =>
                    handleChange(u.email, 'institutional_code', e.target.value)
                  }
                >
                  <option value="">Select...</option>
                  {codes.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
                  ))}
                </select>
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
                <button className="delete-button" onClick={() => handleDelete(u.email)} style={{marginLeft: '0.5rem'}}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default AdminUsers;
