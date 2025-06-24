import React, { useState, useEffect } from 'react';
import api from './api';
import { Link, useNavigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import './StudentProfiles.css';

function StudentProfiles() {
  // Manual form state
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
  const [formMessage, setFormMessage] = useState('');
  const [formError, setFormError] = useState('');

  // CSV upload state
  const [csvFile, setCsvFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadResult, setUploadResult] = useState('');
  const [uploadError, setUploadError] = useState('');

  // Resume upload state
  const [resumeFile, setResumeFile] = useState(null);

  // Students from this user's school
  const [schoolStudents, setSchoolStudents] = useState([]);

  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');
  const { role } = token ? jwtDecode(token) : {};

  useEffect(() => {
    const fetchStudents = async () => {
      try {
        const resp = await api.get('/students/by-school', {
          headers: { Authorization: `Bearer ${token}` },
        });
        setSchoolStudents(resp.data?.students || []);
      } catch (err) {
        console.error('Failed to fetch students:', err);
      }
    };

    if (token) {
      fetchStudents();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormMessage('');
    setFormError('');
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
      await api.post('/students', studentData, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      setFormMessage('Student profile submitted!');
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
    } catch (err) {
      console.error('Submission failed:', err);
      setFormError('Submission failed. Please check all required fields.');
    }
  };

  const handleFileChange = (e) => {
    setCsvFile(e.target.files[0]);
    setUploadProgress(0);
    setUploadResult('');
    setUploadError('');
  };

  const handleResumeChange = (e) => {
    setResumeFile(e.target.files[0] || null);
  };


  const handleUpload = async () => {
    if (!csvFile) return;
    setUploadProgress(0);
    setUploadResult('');
    setUploadError('');
    const data = new FormData();
    data.append('file', csvFile);
    try {
      const resp = await api.post('/students/upload', data, {
        headers: {
          'Content-Type': 'multipart/form-data',
          Authorization: `Bearer ${token}`
        },
        onUploadProgress: (p) => {
          if (p.total) {
            setUploadProgress(Math.round((p.loaded * 100) / p.total));
          }
        }
      });
      setUploadResult(resp.data.message);
    } catch (err) {
      setUploadError(err.response?.data?.detail || 'Upload failed');
    }
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
            {role === 'admin' && (
              <button
                className="admin-reset-button"
                onClick={async () => {
                  if (
                    window.confirm(
                      'Are you sure you want to delete ALL jobs and match data?'
                    )
                  ) {
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
      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          width: '100%',
          gap: '2rem',
          boxSizing: 'border-box',
          height: '100%',
        }}
      >
        <div
          className="form-section"
          style={{ flex: 0.6, maxWidth: '700px', overflowX: 'hidden' }}
        >
          <h2>New Student Profile</h2>
          <form className="profile-form" onSubmit={handleSubmit}>
          <label htmlFor="first_name">First Name</label>
          <input
            id="first_name"
            name="first_name"
            type="text"
            value={formData.first_name}
            onChange={handleChange}
          />

          <label htmlFor="last_name">Last Name</label>
          <input
            id="last_name"
            name="last_name"
            type="text"
            value={formData.last_name}
            onChange={handleChange}
          />

          <label htmlFor="email">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            value={formData.email}
            onChange={handleChange}
          />

          <label htmlFor="phone">Phone</label>
          <input
            id="phone"
            name="phone"
            type="text"
            value={formData.phone}
            onChange={handleChange}
          />

          <label htmlFor="education_level">Education Level</label>
          <input
            id="education_level"
            name="education_level"
            type="text"
            value={formData.education_level}
            onChange={handleChange}
          />

          <label htmlFor="skills">Skills (comma separated)</label>
          <input
            id="skills"
            name="skills"
            type="text"
            value={formData.skills}
            onChange={handleChange}
          />

          <label htmlFor="experience_summary">Experience Summary</label>
          <textarea
            id="experience_summary"
            name="experience_summary"
            value={formData.experience_summary}
            onChange={handleChange}
          ></textarea>

          <label htmlFor="interests">Interests</label>
          <input
            id="interests"
            name="interests"
            type="text"
            value={formData.interests}
            onChange={handleChange}
          />

          <label htmlFor="resume">Upload Resume (PDF or DOCX)</label>
          <input
            id="resume"
            name="resume"
            type="file"
            accept=".pdf,.doc,.docx"
            onChange={handleResumeChange}
          />

          <button type="submit">Submit</button>
          {formMessage && <p className="message">{formMessage}</p>}
          {formError && <p className="error">{formError}</p>}
          </form>
        </div>

        <div
          className="rightColumn"
          style={{
            display: 'flex',
            flexDirection: 'column',
            flex: 0.4,
            height: '100%',
            flexGrow: 1,
          }}
        >


          <div
            className="school-students-section"
            style={{ flexGrow: 1, minHeight: 0, marginTop: '3rem' }}
          >
            <h2>Students from Your School</h2>
            {schoolStudents.length > 0 ? (
              <table className="school-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Education Level</th>
                <th>Assigned Jobs</th>
                <th>Placement Status</th>
              </tr>
            </thead>
            <tbody>
              {schoolStudents.map((s) => {
                const assigned = s.assigned_jobs
                  ? Array.isArray(s.assigned_jobs)
                    ? s.assigned_jobs.length
                    : s.assigned_jobs
                  : 0;
                const placedCount = s.placed_jobs
                  ? Array.isArray(s.placed_jobs)
                    ? s.placed_jobs.length
                    : s.placed_jobs
                  : 0;
                return (
                  <tr key={s.email || `${s.first_name}-${s.last_name}`}>
                    <td>{s.first_name} {s.last_name}</td>
                    <td>{s.education_level}</td>
                    <td>{assigned}</td>
                    <td>{placedCount > 0 ? '✅' : '❌'}</td>
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

