import React, { useState, useEffect } from 'react';
import api from './api';
import { Link, useNavigate } from 'react-router-dom';
import jwt_decode from 'jwt-decode';
import './StudentProfiles.css';

function StudentProfiles() {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    education_level: '',
    skills: '',
    experience_summary: '',
    interests: ''
  });
  const [formError, setFormError] = useState('');
  const [resumeFile, setResumeFile] = useState(null);
  const [toast, setToast] = useState('');

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const [schoolStudents, setSchoolStudents] = useState([]);
  const [isEditing, setIsEditing] = useState(false);
  const [editingEmail, setEditingEmail] = useState('');

  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');
  const decoded = token ? jwt_decode(token) : {};
  const userRole = decoded?.role;

  const fetchStudents = async () => {
    setIsLoading(true);
    try {
      const endpoint = userRole === 'admin' ? '/students/all' : '/students/by-school';
      const resp = await api.get(endpoint, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setSchoolStudents(resp.data?.students || []);
    } catch (err) {
      console.error('Failed to fetch students:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (token) fetchStudents();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleEdit = (email) => {
    const student = schoolStudents.find((s) => s.email === email);
    if (student) {
      setFormData({
        first_name: student.first_name || '',
        last_name: student.last_name || '',
        email: student.email || '',
        phone: student.phone || '',
        education_level: student.education_level || '',
        skills: Array.isArray(student.skills)
          ? student.skills.join(', ')
          : student.skills || '',
        experience_summary: student.experience_summary || '',
        interests: Array.isArray(student.interests)
          ? student.interests.join(', ')
          : student.interests || '',
      });
      setIsEditing(true);
      setEditingEmail(student.email);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormError('');
    setIsSaving(true);
    const studentData = {
      first_name: formData.first_name,
      last_name: formData.last_name,
      email: formData.email,
      phone: formData.phone,
      education_level: formData.education_level,
      skills: formData.skills.split(',').map((s) => s.trim()),
      experience_summary: formData.experience_summary,
      interests: formData.interests.trim(),
    };
    try {
      const method = isEditing ? 'put' : 'post';
      const url = isEditing ? `/students/${editingEmail}` : '/students';
      await api[method](url, studentData, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      const msg = isEditing ? 'Student profile updated!' : 'Student profile submitted!';
      setToast(msg);
      setTimeout(() => setToast(''), 3000);
      setFormData({
        first_name: '',
        last_name: '',
        email: '',
        phone: '',
        education_level: '',
        skills: '',
        experience_summary: '',
        interests: ''
      });
      setResumeFile(null);
      setIsEditing(false);
      setEditingEmail('');
      fetchStudents();
    } catch (err) {
      console.error('Submission failed:', err);
      setFormError('Submission failed. Please check all required fields.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleResumeChange = (e) => {
    setResumeFile(e.target.files[0] || null);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="profiles-container">
      <div className="admin-menu">
        <button className="menu-button" onClick={() => setMenuOpen((o) => !o)}>
          Admin Menu
        </button>
        {menuOpen && (
          <div className="dropdown-menu">
            <Link to="/dashboard">Dashboard</Link>
            <Link to="/admin/pending">Pending Approvals</Link>
            <Link to="/students">Student Profiles</Link>
            {userRole === 'admin' && (
              <button
                className="admin-reset-button"
                onClick={async () => {
                  if (window.confirm('Are you sure you want to delete ALL jobs and match data?')) {
                    try {
                      const resp = await api.delete('/admin/reset-jobs', {
                        headers: { Authorization: `Bearer ${token}` },
                      });
                      alert(resp.data.message);
                    } catch (err) {
                      console.error('Reset failed:', err);
                      alert('Failed to reset jobs.');
                    }
                  }
                }}
              >
                🧨 Reset All Jobs
              </button>
            )}
            <button onClick={handleLogout}>Logout</button>
          </div>
        )}
      </div>

      {toast && <div className="toast">{toast}</div>}

      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          width: '100%',
          minHeight: '100vh',
          gap: '2rem',
        }}
      >
        <div style={{ flex: 1, maxWidth: '600px' }}>
          <h2>{isEditing ? 'Edit Student Profile' : 'New Student Profile'}</h2>
          <form className="profile-form" onSubmit={handleSubmit}>
            {['first_name', 'last_name', 'email', 'phone', 'education_level', 'skills', 'experience_summary', 'interests'].map((field) => (
              <React.Fragment key={field}>
                <label htmlFor={field}>{field.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</label>
                {field === 'experience_summary' ? (
                  <textarea
                    id={field}
                    name={field}
                    value={formData[field]}
                    onChange={handleChange}
                  />
                ) : (
                  <input
                    id={field}
                    name={field}
                    type="text"
                    value={formData[field]}
                    onChange={handleChange}
                  />
                )}
              </React.Fragment>
            ))}
            <label htmlFor="resume">Upload Resume (PDF or DOCX)</label>
            <input id="resume" name="resume" type="file" onChange={handleResumeChange} />
            <button type="submit" disabled={isSaving}>
              {isSaving ? (
                <>
                  <span className="spinner" /> Saving...
                </>
              ) : (
                isEditing ? 'Update' : 'Submit'
              )}
            </button>
            {formError && <p className="error">{formError}</p>}
          </form>
        </div>

        <div
          className="rightColumn"
          style={{
            flex: 1,
            minWidth: '600px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'flex-start',
          }}
        >
          <div style={{ flexGrow: 1, minHeight: 0, marginTop: '3rem' }}>
            <h2>Students from Your School</h2>
            {isLoading ? (
              <div className="loading-container">
                <span className="spinner" />
                <span style={{ marginLeft: '0.5rem' }}>Loading students...</span>
              </div>
            ) : schoolStudents.length > 0 ? (
              <table className="school-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    {userRole === 'admin' && <th>School</th>}
                    <th>Edit</th>
                    <th>Assigned Jobs</th>
                    <th>Placement Status</th>
                  </tr>
                </thead>
                <tbody>
                  {schoolStudents.map((s) => {
                    const assigned = Array.isArray(s.assigned_jobs) ? s.assigned_jobs.length : s.assigned_jobs || 0;
                    const placed = Array.isArray(s.placed_jobs) ? s.placed_jobs.length : s.placed_jobs || 0;
                    return (
                      <tr key={s.email}>
                        <td>{s.first_name} {s.last_name}</td>
                        {userRole === 'admin' && <td>{s.school_code}</td>}
                        <td>
                          <button onClick={() => handleEdit(s.email)} style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            fontSize: '1.2rem',
                          }} title="Edit">✏️</button>
                        </td>
                        <td>{assigned}</td>
                        <td>{placed > 0 ? '✅' : '❌'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p>No students found for your school.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default StudentProfiles;
