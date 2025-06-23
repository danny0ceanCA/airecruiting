import React, { useState } from 'react';
import api from './api';
import { Link, useNavigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import './StudentProfiles.css';

function StudentProfiles() {
  // Manual form state
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    phone: '',
    educationLevel: '',
    skills: '',
    experienceSummary: '',
    interests: ''
  });
  const [formMessage, setFormMessage] = useState('');
  const [formError, setFormError] = useState('');
  const [parseMessage, setParseMessage] = useState('');
  const [parseError, setParseError] = useState('');

  // CSV upload state
  const [csvFile, setCsvFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadResult, setUploadResult] = useState('');
  const [uploadError, setUploadError] = useState('');

  // Resume upload state
  const [resumeFile, setResumeFile] = useState(null);

  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');
  const { role } = token ? jwtDecode(token) : {};

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormMessage('');
    setFormError('');
    const payload = {
      first_name: formData.firstName,
      last_name: formData.lastName,
      email: formData.email,
      phone: formData.phone,
      education_level: formData.educationLevel,
      skills: formData.skills
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      experience_summary: formData.experienceSummary,
      interests: formData.interests
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    };
    try {
      await api.post('/students', payload, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      setFormMessage('Student profile submitted!');
      setFormData({
        firstName: '',
        lastName: '',
        email: '',
        phone: '',
        educationLevel: '',
        skills: '',
        experienceSummary: '',
        interests: ''
      });
      setResumeFile(null);
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Submission failed');
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

  const handleParseResume = async () => {
    if (!resumeFile) return;
    setParseMessage('');
    setParseError('');
    const data = new FormData();
    data.append('resume', resumeFile);
    try {
      const resp = await api.post('/parse-resume', data, {
        headers: {
          'Content-Type': 'multipart/form-data',
          Authorization: `Bearer ${token}`,
        },
      });
      const p = resp.data || {};
      setFormData({
        firstName: p.first_name || '',
        lastName: p.last_name || '',
        email: p.email || '',
        phone: p.phone || '',
        educationLevel: p.education_level || '',
        skills: Array.isArray(p.skills) ? p.skills.join(', ') : p.skills || '',
        experienceSummary: p.experience_summary || '',
        interests: Array.isArray(p.interests)
          ? p.interests.join(', ')
          : p.interests || '',
      });
      setParseMessage('Profile filled from resume. Please review before submitting.');
    } catch (err) {
      setParseError(err.response?.data?.detail || 'Failed to parse resume');
    }
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
      <div className="form-section">
        <h2>New Student Profile</h2>
        <form className="profile-form" onSubmit={handleSubmit}>
          <label htmlFor="firstName">First Name</label>
          <input
            id="firstName"
            name="firstName"
            type="text"
            value={formData.firstName}
            onChange={handleChange}
          />

          <label htmlFor="lastName">Last Name</label>
          <input
            id="lastName"
            name="lastName"
            type="text"
            value={formData.lastName}
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

          <label htmlFor="educationLevel">Education Level</label>
          <input
            id="educationLevel"
            name="educationLevel"
            type="text"
            value={formData.educationLevel}
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

          <label htmlFor="experienceSummary">Experience Summary</label>
          <textarea
            id="experienceSummary"
            name="experienceSummary"
            value={formData.experienceSummary}
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
          <button type="button" onClick={handleParseResume} disabled={!resumeFile}>
            Parse Resume with AI
          </button>
          {parseMessage && <p className="message">{parseMessage}</p>}
          {parseError && <p className="error">{parseError}</p>}

          <button type="submit">Submit</button>
          {formMessage && <p className="message">{formMessage}</p>}
          {formError && <p className="error">{formError}</p>}
        </form>
      </div>

      <div className="upload-section">
        <h2>Upload CSV</h2>
        <input type="file" accept=".csv" onChange={handleFileChange} />
        <button onClick={handleUpload} disabled={!csvFile}>Upload</button>
        {uploadProgress > 0 && <p>Progress: {uploadProgress}%</p>}
        {uploadResult && <p className="message">{uploadResult}</p>}
        {uploadError && <p className="error">{uploadError}</p>}
      </div>
    </div>
  );
}

export default StudentProfiles;

