import React, { useState, useEffect } from 'react';
import api from './api';
import { Link, useNavigate } from 'react-router-dom';
import jwt_decode from 'jwt-decode';
import jsPDF from 'jspdf';
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

  const [generatingDescriptions, setGeneratingDescriptions] = useState({});
  const [generatedDescriptions, setGeneratedDescriptions] = useState({});

  const [menuOpen, setMenuOpen] = useState(false);
  const [expandedRows, setExpandedRows] = useState({});
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

  const toggleRow = (email) => {
    setExpandedRows((prev) => ({
      ...prev,
      [email]: !prev[email],
    }));
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

  const handleMarkPlaced = async (student) => {
    try {
      await api.post(
        '/place',
        {
          student_email: student.email,
          job_code: student.assigned_job_code,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setToast('\u2705 Marked as Placed');
      setTimeout(() => setToast(''), 3000);
      fetchStudents();
    } catch (err) {
      console.error('Placement failed:', err);
    }
  };

  const generateDescription = async (studentEmail, job) => {
    const key = `${job.job_code}:${studentEmail}`;
    if (generatedDescriptions[key]) return;
    setGeneratingDescriptions((prev) => ({ ...prev, [key]: true }));
    try {
      const resp = await api.post(
        '/generate-description',
        { student_email: studentEmail, job_code: job.job_code },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (resp.data.status === 'success' || resp.data.status === 'exists') {
        setGeneratedDescriptions((prev) => ({ ...prev, [key]: true }));
      }
    } catch (err) {
      console.error('Description generation failed:', err);
    } finally {
      setGeneratingDescriptions((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleDownloadJobDescriptionPDF = async (jobCode, studentEmail, studentName) => {
    try {
      const resp = await api.get(`/resume/${jobCode}/${studentEmail}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      const text = resp.data.resume;
      const doc = new jsPDF();

      // Header: TalentMatch AI
      doc.setFontSize(18);
      doc.setFont('helvetica', 'bold');
      doc.text('TalentMatch AI', 105, 20, { align: 'center' });

      // Body
      doc.setFontSize(12);
      doc.setFont('helvetica', 'normal');
      const lines = doc.splitTextToSize(text, 180);
      doc.text(lines, 15, 40);

      const fileName = `Job_Summary_${studentName.replace(/\s+/g, '_')}_${jobCode}.pdf`;
      doc.save(fileName);
    } catch (err) {
      console.error('Failed to generate job summary PDF:', err);
      alert('Could not download job summary.');
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
                    <th></th>
                    <th>Name</th>
                    {userRole === 'admin' && <th>School</th>}
                    <th>Edit</th>
                    <th>Assigned Jobs</th>
                    <th>Placement Status</th>
                    <th>Placement Controls</th>
                  </tr>
                </thead>
                <tbody>
                  {schoolStudents.map((s) => {
                    const assigned = Array.isArray(s.assigned_jobs) ? s.assigned_jobs.length : s.assigned_jobs || 0;
                    const placed = Array.isArray(s.placed_jobs) ? s.placed_jobs.length : s.placed_jobs || 0;
                    return (
                      <React.Fragment key={s.email}>
                        <tr>
                          <td>
                            <span
                              className="expand-toggle"
                              onClick={() => toggleRow(s.email)}
                              title={expandedRows[s.email] ? 'Collapse' : 'Expand'}
                            >
                              {expandedRows[s.email] ? '–' : '+'}
                            </span>
                          </td>
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
                          <td>
                            {assigned > 0 && placed === 0 && userRole !== 'admin' && (
                              <button onClick={() => handleMarkPlaced(s)}>
                                Mark as Placed
                              </button>
                            )}
                          </td>
                        </tr>
                        {expandedRows[s.email] && (
                          <tr className="job-subrow" key={`${s.email}-jobs`}>
                            <td colSpan="100%">
                              <table className="job-subtable">
                                <thead>
                                  <tr>
                                    <th>Job Title</th>
                                    <th>Job Code</th>
                                    <th>Source</th>
                                    <th>Job Description</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {s.assigned_jobs && s.assigned_jobs.length > 0 ? (
                                    s.assigned_jobs.map((job, index) => (
                                      <tr key={index}>
                                        <td>{job.job_title}</td>
                                        <td>{job.job_code}</td>
                                        <td>{job.source}</td>
                                        <td>
                                          {userRole === 'user' && (
                                            <button
                                              onClick={() =>
                                                handleDownloadJobDescriptionPDF(
                                                  job.job_code,
                                                  s.email,
                                                  `${s.first_name} ${s.last_name}`
                                                )
                                              }
                                              style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                                              title="Generate Job Description PDF"
                                            >
                                              📄
                                            </button>
                                          )}
                                          {userRole === 'user' && (
                                            generatingDescriptions[`${job.job_code}:${s.email}`] ? (
                                              <div style={{ display: 'flex', justifyContent: 'center' }}>
                                                <span className="spinner" />
                                              </div>
                                            ) : generatedDescriptions[`${job.job_code}:${s.email}`] ? (
                                              <span title="Done">✅</span>
                                            ) : (
                                              <button
                                                className="desc-icon-button"
                                                title="Generate Job Description"
                                                onClick={() => generateDescription(s.email, job)}
                                              >
                                                📝
                                              </button>
                                            )
                                          )}
                                        </td>
                                      </tr>
                                    ))
                                  ) : (
                                    <tr className="no-jobs-row">
                                      <td colSpan="4">No jobs assigned by recruiters.</td>
                                    </tr>
                                  )}
                                </tbody>
                              </table>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
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
