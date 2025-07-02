import React, { useState, useEffect, useRef } from 'react';
import api from './api';
import loadGoogleMaps from './utils/loadGoogleMaps';

import AdminMenu from './AdminMenu';
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
    interests: '',
    city: '',
    state: '',
    lat: '',
    lng: '',
    max_travel: ''
  });
  const [formError, setFormError] = useState('');
  const [resumeFile, setResumeFile] = useState(null);
  const [toast, setToast] = useState('');

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const [schoolStudents, setSchoolStudents] = useState([]);
  const [firstNameFilter, setFirstNameFilter] = useState('');
  const [lastNameFilter, setLastNameFilter] = useState('');
  const [emailFilter, setEmailFilter] = useState('');
  const [codeFilter, setCodeFilter] = useState('');
  const [placementFilter, setPlacementFilter] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [editingEmail, setEditingEmail] = useState('');

  const [activeTab, setActiveTab] = useState('students');

  const [jobDescriptionStatus, setJobDescriptionStatus] = useState({});

  const [expandedRows, setExpandedRows] = useState({});

  const cityRef = useRef(null);

  const initAutocomplete = () => {
    if (cityRef.current && window.google) {
      const ac = new window.google.maps.places.Autocomplete(cityRef.current, { types: ['(cities)'] });
      ac.addListener('place_changed', () => {
        const place = ac.getPlace();
        const comps = place.address_components || [];
        const city = comps.find(c => c.types.includes('locality'))?.long_name || '';
        const state = comps.find(c => c.types.includes('administrative_area_level_1'))?.short_name || '';
        const lat = place.geometry.location.lat();
        const lng = place.geometry.location.lng();
        setFormData(prev => ({ ...prev, city, state, lat, lng }));
      });
    }
  };

  useEffect(() => {
    loadGoogleMaps(initAutocomplete);
  }, []);

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

  const toggleRow = (email, assignedJobs = []) => {
    setExpandedRows((prev) => {
      const expanded = !prev[email];
      if (!prev[email]) {
        for (const job of assignedJobs) {
          fetchJobDescriptionStatus(email, job.job_code);
        }
      }
      return { ...prev, [email]: expanded };
    });
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
        city: student.city || '',
        state: student.state || '',
        lat: student.lat || '',
        lng: student.lng || '',
        max_travel: student.max_travel || '',
      });
      setIsEditing(true);
      setEditingEmail(student.email);
      setActiveTab('new');
    }
  };

  const handleDelete = async (email) => {
    if (!window.confirm(`Are you sure you want to delete ${email}? This cannot be undone.`)) return;
    try {
      await api.delete(`/admin/delete-student/${email}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      alert(`Deleted ${email}`);
      fetchStudents(); // Refresh table
    } catch (err) {
      console.error("Delete failed:", err);
      alert("Failed to delete student.");
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

  const [loadingJobDescriptions, setLoadingJobDescriptions] = useState({});

  const fetchJobDescriptionStatus = async (studentEmail, jobCode) => {
    try {
      const resp = await api.get(`/job-description/${jobCode}/${studentEmail}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.data.status === 'success') {
        setJobDescriptionStatus(prev => ({
          ...prev,
          [jobCode]: 'ready',
        }));
      }
    } catch (err) {
      // leave undefined if not found
    }
  };

  const generateJobDescription = async (jobCode, studentEmail) => {
    setLoadingJobDescriptions((prev) => ({ ...prev, [jobCode]: true }));
    try {
      await api.post(
        '/generate-job-description',
        { job_code: jobCode, student_email: studentEmail },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setJobDescriptionStatus((prev) => ({ ...prev, [jobCode]: 'ready' }));
    } catch (err) {
      console.error('Generation failed', err);
    } finally {
      setLoadingJobDescriptions((prev) => ({ ...prev, [jobCode]: false }));
    }
  };

  const handleGenerateJobDescription = (jobCode, studentEmail) => {
    generateJobDescription(jobCode, studentEmail);
  };

  const viewJobDescription = async (jobCode, studentEmail) => {
    try {
      const resp = await api.get(`/job-description-html/${jobCode}/${studentEmail}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const newWindow = window.open('', '_blank');
      if (newWindow) {
        newWindow.document.write(resp.data);
        newWindow.document.close();
      }
    } catch (err) {
      alert("Failed to load job description.");
      console.error(err);
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
      city: formData.city,
      state: formData.state,
      lat: parseFloat(formData.lat || 0),
      lng: parseFloat(formData.lng || 0),
      max_travel: parseFloat(formData.max_travel || 0),
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
        interests: '',
        city: '',
        state: '',
        lat: '',
        lng: '',
        max_travel: ''
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


  const filteredStudents = schoolStudents.filter((s) => {
    const firstMatch = s.first_name
      ?.toLowerCase()
      .includes(firstNameFilter.toLowerCase());
    const lastMatch = s.last_name
      ?.toLowerCase()
      .includes(lastNameFilter.toLowerCase());
    const emailMatch = s.email
      ?.toLowerCase()
      .includes(emailFilter.toLowerCase());
    const codeMatch =
      userRole !== 'admin'
        ? true
        : (s.institutional_code || '')
            .toLowerCase()
            .includes(codeFilter.toLowerCase());
    const placed = Array.isArray(s.placed_jobs)
      ? s.placed_jobs.length
      : s.placed_jobs || 0;
    let placementMatch = true;
    if (placementFilter === '✅') placementMatch = placed > 0;
    if (placementFilter === '❌') placementMatch = placed === 0;
    return firstMatch && lastMatch && emailMatch && codeMatch && placementMatch;
  });

  return (
    <div className="profiles-container">
      <AdminMenu>
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
      </AdminMenu>

      {toast && <div className="toast">{toast}</div>}

      <div className="tab-bar">
        <button
          className={`tab ${activeTab === 'students' ? 'active' : ''}`}
          onClick={() => setActiveTab('students')}
        >
          Students
        </button>
        <button
          className={`tab ${activeTab === 'new' ? 'active' : ''}`}
          onClick={() => setActiveTab('new')}
        >
          New Student Profile
        </button>
      </div>

      <div className="tab-content">
        {activeTab === 'new' && (
          <div className="form-panel">
            <h2>{isEditing ? 'Edit Student Profile' : 'New Student Profile'}</h2>
            <form className="profile-form" onSubmit={handleSubmit}>
            {['first_name', 'last_name', 'email', 'phone', 'education_level', 'skills', 'experience_summary', 'interests', 'city', 'state', 'lat', 'lng', 'max_travel'].map((field) => (
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
                    type={field === 'max_travel' ? 'number' : 'text'}
                    value={formData[field]}
                    onChange={handleChange}
                    readOnly={['lat','lng','state'].includes(field)}
                    ref={field === 'city' ? cityRef : null}
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
        )}
        {activeTab === 'students' && (
        <div
          className="students-panel"
          style={{
            flex: 1,
            minWidth: '600px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'flex-start',
          }}
        >
          <div style={{ flexGrow: 1, minHeight: 0, marginTop: '0' }}>
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
                    <th>First Name</th>
                    <th>Last Name</th>
                    <th>Email</th>
                    {userRole === 'admin' && <th>School</th>}
                    <th>Edit</th>
                    <th>Assigned Jobs</th>
                    <th>Placement Status</th>
                    <th>Placement Controls</th>
                  </tr>
                  <tr className="filter-row">
                    <th></th>
                    <th>
                      <input
                        className="column-filter"
                        type="text"
                        value={firstNameFilter}
                        onChange={(e) => setFirstNameFilter(e.target.value)}
                        placeholder="Filter"
                      />
                    </th>
                    <th>
                      <input
                        className="column-filter"
                        type="text"
                        value={lastNameFilter}
                        onChange={(e) => setLastNameFilter(e.target.value)}
                        placeholder="Filter"
                      />
                    </th>
                    <th>
                      <input
                        className="column-filter"
                        type="text"
                        value={emailFilter}
                        onChange={(e) => setEmailFilter(e.target.value)}
                        placeholder="Filter"
                      />
                    </th>
                    {userRole === 'admin' && (
                      <th>
                        <input
                          className="column-filter"
                          type="text"
                          value={codeFilter}
                          onChange={(e) => setCodeFilter(e.target.value)}
                          placeholder="Filter"
                        />
                      </th>
                    )}
                    <th></th>
                    <th></th>
                    <th>
                      <select
                        className="column-filter"
                        value={placementFilter}
                        onChange={(e) => setPlacementFilter(e.target.value)}
                      >
                        <option value="">All</option>
                        <option value="✅">✅</option>
                        <option value="❌">❌</option>
                      </select>
                    </th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredStudents.map((s) => {
                    const assigned = Array.isArray(s.assigned_jobs) ? s.assigned_jobs.length : s.assigned_jobs || 0;
                    const placed = Array.isArray(s.placed_jobs) ? s.placed_jobs.length : s.placed_jobs || 0;
                    return (
                      <React.Fragment key={s.email}>
                        <tr>
                          <td>
                            <span
                              className="expand-toggle"
                              onClick={() => toggleRow(s.email, s.assigned_jobs)}
                              title={expandedRows[s.email] ? 'Collapse' : 'Expand'}
                            >
                              {expandedRows[s.email] ? '–' : '+'}
                            </span>
                          </td>
                          <td>{s.first_name}</td>
                          <td>{s.last_name}</td>
                          <td>{s.email}</td>
                          {userRole === 'admin' && <td>{s.institutional_code}</td>}
                          <td>
                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                              <button
                                onClick={() => handleEdit(s.email)}
                                style={{
                                  background: 'none',
                                  border: 'none',
                                  cursor: 'pointer',
                                  fontSize: '1.2rem',
                                }}
                                title="Edit"
                              >
                                ✏️
                              </button>
                              {userRole === 'admin' && (
                                <button
                                  onClick={() => handleDelete(s.email)}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    fontSize: '1.2rem',
                                    color: 'red',
                                  }}
                                  title="Delete Student"
                                >
                                  🗑️
                                </button>
                              )}
                            </div>
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
                                    <th>Rate</th>
                                    <th>Source</th>
                                    <th>Job Description</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {s.assigned_jobs && s.assigned_jobs.length > 0 ? (
                                    s.assigned_jobs.map((job, index) => (
                                      <tr key={index}>
                                        <td>{job.job_title}</td>
                                        <td>
                                          {job.min_pay && job.max_pay
                                            ? `${job.min_pay} - ${job.max_pay}`
                                            : 'N/A'}
                                        </td>
                                        <td>{job.source || 'N/A'}</td>
                                        <td style={{ textAlign: 'center' }}>
                                          {loadingJobDescriptions[job.job_code] ? (
                                            <span>Generating...</span>
                                          ) : jobDescriptionStatus[job.job_code] === 'ready' ? (
                                            <button
                                              style={{
                                                padding: '4px 10px',
                                                fontSize: '14px',
                                                border: '1px solid #ccc',
                                                borderRadius: '4px',
                                                backgroundColor: '#f5f5f5',
                                                cursor: 'pointer'
                                              }}
                                              onClick={() => viewJobDescription(job.job_code, s.email)}
                                              className="view-btn"
                                            >
                                              View Job Description
                                            </button>
                                          ) : (
                                            <button
                                              style={{
                                                padding: '4px 10px',
                                                fontSize: '14px',
                                                border: '1px solid #ccc',
                                                borderRadius: '4px',
                                                backgroundColor: '#f5f5f5',
                                                cursor: 'pointer'
                                              }}
                                              onClick={() => handleGenerateJobDescription(job.job_code, s.email)}
                                            >
                                              Load Job Description
                                            </button>
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
        )}
      </div>
    </div>
  );
}

export default StudentProfiles;
