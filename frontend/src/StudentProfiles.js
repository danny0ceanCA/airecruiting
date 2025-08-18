import React, { useState, useEffect, useRef } from 'react';
import Joyride from 'react-joyride';
import api from './api';
import loadGoogleMaps from './utils/loadGoogleMaps';
import { useNavigate } from 'react-router-dom';

import AdminMenu from './AdminMenu';
import jwt_decode from 'jwt-decode';
import './StudentProfiles.css';
import './Tour.css';
import NotesHistoryModal from './NotesHistoryModal';
import Tooltip from './components/Tooltip';

function StudentProfiles() {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    license: '',
    skills: '',
    experience_summary: '',
    interests: '',
    city: '',
    state: '',
    lat: '',
    lng: '',
    max_travel: ''
  });
  const [licenses, setLicenses] = useState([]);
  const licenseLabel = (code) => {
    const l = licenses.find((x) => x.code === code);
    return l ? l.label : code;
  };
  const [formError, setFormError] = useState('');
  const [resumeFile, setResumeFile] = useState(null);
  const [toast, setToast] = useState('');

  const [showTour, setShowTour] = useState(
    localStorage.getItem('studentTourSeen') !== 'true'
  );

  const tourSteps = [
    {
      target: '.tab-bar',
      content: 'Use these tabs to switch between the student list and adding a new profile.'
    },
    {
      target: '.new-tab',
      content: "Click 'New Student Profile' when you need to add a student."
    },
    {
      target: '.profile-form',
      content:
        "Fill in the student's contact info, skills, and travel range here."
    },
    {
      target: '.filter-row',
      content:
        'Filter the list by any column to quickly find students.'
    },
    {
      target: '.expand-toggle',
      content:
        'Click the plus sign to see all jobs assigned to that student and view details.'
    },
    {
      target: '.edit-col',
      content: 'Use the pencil to edit or the trash can to remove a profile.'
    },
    {
      target: '.assigned-col',
      content: 'Shows how many jobs are assigned to each student.'
    },
    {
      target: '.placement-status-col',
      content: 'A check means placed. An X means still looking.'
    },
    {
      target: '.placement-controls-col',
      content: 'Mark a student as placed when they accept a job.'
    }
  ];

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const [schoolStudents, setSchoolStudents] = useState([]);
  const [firstNameFilter, setFirstNameFilter] = useState('');
  const [lastNameFilter, setLastNameFilter] = useState('');
  const [emailFilter, setEmailFilter] = useState('');
  const [locationFilter, setLocationFilter] = useState('');
  const [codeFilter, setCodeFilter] = useState('');
  const [licenseFilter, setLicenseFilter] = useState('');
  const [assignedFilter, setAssignedFilter] = useState('');
  const [placementFilter, setPlacementFilter] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [editingEmail, setEditingEmail] = useState('');

  const [activeTab, setActiveTab] = useState('students');

  const [jobDescriptionStatus, setJobDescriptionStatus] = useState({});

  const [expandedRows, setExpandedRows] = useState({});
  const [modalNotes, setModalNotes] = useState(null);

  const handleTourCallback = (data) => {
    const { status, type } = data;
    if (status === 'finished' || status === 'skipped') {
      localStorage.setItem('studentTourSeen', 'true');
      setShowTour(false);
    }
  };

  const cityRef = useRef(null);
  const tableWrapperRef = useRef(null);
  const headerRowRef = useRef(null);

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
  }, [activeTab, isEditing]);

  useEffect(() => {
    const wrapper = tableWrapperRef.current;
    if (!wrapper) return;

    const handleScroll = () => {
      if (wrapper.scrollTop > 0) {
        wrapper.classList.add('scrolled');
      } else {
        wrapper.classList.remove('scrolled');
      }
    };

    wrapper.addEventListener('scroll', handleScroll);
    return () => wrapper.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    const header = headerRowRef.current;
    const wrapper = tableWrapperRef.current;
    if (header && wrapper) {
      const height = header.getBoundingClientRect().height;
      wrapper.style.setProperty('--header-height', `${height}px`);
    }
  }, [schoolStudents, activeTab]);

  const navigate = useNavigate();
  const token = localStorage.getItem('token');
  let decoded = {};
  try {
    decoded = token ? jwt_decode(token) : {};
  } catch (err) {
    decoded = {};
  }
  const userRole = decoded?.role;
  const isAdmin = userRole === 'admin';

  const fetchStudents = async () => {
    setIsLoading(true);
    try {
      const endpoint = userRole === 'admin' ? '/students/all' : '/students/by-school';
      const resp = await api.get(endpoint, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setSchoolStudents(resp.data?.students || []);
    } catch (err) {
      if (err.response && err.response.status === 401) {
        localStorage.removeItem('token');
        navigate('/login');
      } else {
        console.error('Failed to fetch students:', err);
        setToast('Failed to load students. Please try again later.');
        setTimeout(() => setToast(''), 3000);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const fetchLicenses = async () => {
    try {
      const resp = await api.get('/licenses');
      setLicenses(resp.data.licenses || []);
    } catch (err) {
      console.error('Failed to fetch licenses:', err);
    }
  };

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return;
    }
    try {
      const { exp } = jwt_decode(token);
      if (exp && Date.now() >= exp * 1000) {
        localStorage.removeItem('token');
        navigate('/login');
        return;
      }
    } catch (err) {
      navigate('/login');
      return;
    }
    fetchLicenses();
    fetchStudents();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const toggleRow = (email, assignedJobs = []) => {
    setExpandedRows((prev) => {
      const isOpen = prev[email] === 'open';
      if (!isOpen) {
        for (const job of assignedJobs) {
          fetchJobDescriptionStatus(email, job.job_code);
        }
        return { ...prev, [email]: 'open' };
      } else {
        setTimeout(() => {
          setExpandedRows((cur) => {
            const updated = { ...cur };
            delete updated[email];
            return updated;
          });
        }, 250);
        return { ...prev, [email]: 'closing' };
      }
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
        license: student.license || student.education_level || '',
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
      license: formData.license,
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
        license: '',
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
    const locationMatch = `${s.city || ''} ${s.state || ''}`
      .toLowerCase()
      .includes(locationFilter.toLowerCase());
    const codeMatch =
      userRole !== 'admin'
        ? true
        : (s.institutional_code || '')
            .toLowerCase()
            .includes(codeFilter.toLowerCase());
    const licenseMatch =
      !licenseFilter || (s.license || '').toLowerCase() === licenseFilter.toLowerCase();
    const assignedCount = Array.isArray(s.assigned_jobs)
      ? s.assigned_jobs.length
      : s.assigned_jobs || 0;
    const assignedMatch =
      assignedFilter === ''
        ? true
        : assignedCount.toString().includes(assignedFilter.toString());
    const placed = Array.isArray(s.placed_jobs)
      ? s.placed_jobs.length
      : s.placed_jobs || 0;
    let placementMatch = true;
    if (placementFilter === '✅') placementMatch = placed > 0;
    if (placementFilter === '❌') placementMatch = placed === 0;
    return (
      firstMatch &&
      lastMatch &&
      emailMatch &&
      locationMatch &&
      codeMatch &&
      licenseMatch &&
      assignedMatch &&
      placementMatch
    );
  });

  return (

    <div
      className="glass-panel"
      style={{ borderRadius: '1.25rem', overflow: 'hidden', width: '100%' }}
    >
      <div className="profiles-container">
        {showTour && (
          <Joyride
            steps={tourSteps}
            continuous
            showSkipButton
            showProgress
            callback={handleTourCallback}
            styles={{ options: { zIndex: 10000 } }}
          />
        )}
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

      {!showTour && (
        <button className="tour-trigger" onClick={() => setShowTour(true)}>
          Take a Tour
        </button>
      )}

      {toast && <div className="toast">{toast}</div>}

      <div className="tab-bar">
        <button
          className={`tab students-tab ${activeTab === 'students' ? 'active' : ''}`}
          onClick={() => setActiveTab('students')}
        >
          Students
        </button>
        <button
          className={`tab new-tab ${activeTab === 'new' ? 'active' : ''}`}
          onClick={() => setActiveTab('new')}
        >
          New Student Profile
        </button>
      </div>

      <div className="tab-content">
        {activeTab === 'new' && (
          <div className="form-panel">
            <form className="profile-form" onSubmit={handleSubmit}>
              <h2>{isEditing ? 'Edit Student Profile' : 'New Student Profile'}</h2>
            <label htmlFor="first_name">First Name</label>
            <input id="first_name" name="first_name" type="text" value={formData.first_name} onChange={handleChange} />
            <label htmlFor="last_name">Last Name</label>
            <input id="last_name" name="last_name" type="text" value={formData.last_name} onChange={handleChange} />
            <label htmlFor="email">Email</label>
            <input id="email" name="email" type="text" value={formData.email} onChange={handleChange} />
            <label htmlFor="phone">Phone</label>
            <input id="phone" name="phone" type="text" value={formData.phone} onChange={handleChange} />
            <label htmlFor="license">License</label>
            <select id="license" name="license" value={formData.license} onChange={handleChange}>
              <option value="">Select...</option>
              {licenses.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
            <label htmlFor="skills">Skills</label>
            <input id="skills" name="skills" type="text" value={formData.skills} onChange={handleChange} />
            <label htmlFor="experience_summary">Experience Summary</label>
            <textarea id="experience_summary" name="experience_summary" value={formData.experience_summary} onChange={handleChange} />
            <label htmlFor="interests">Interests</label>
            <input id="interests" name="interests" type="text" value={formData.interests} onChange={handleChange} />
            <label htmlFor="city">City</label>
            <input id="city" name="city" type="text" value={formData.city} onChange={handleChange} ref={cityRef} />
            <label htmlFor="state">State</label>
            <input id="state" name="state" type="text" value={formData.state} onChange={handleChange} readOnly />
            <label htmlFor="max_travel">Max Travel</label>
            <input id="max_travel" name="max_travel" type="number" value={formData.max_travel} onChange={handleChange} />
            <input type="hidden" id="lat" name="lat" value={formData.lat} readOnly />
            <input type="hidden" id="lng" name="lng" value={formData.lng} readOnly />
            {/* Uploading documents is temporarily disabled */}
            {false && (
              <>
                <label htmlFor="resume">Upload Resume (PDF or DOCX)</label>
                <input id="resume" name="resume" type="file" onChange={handleResumeChange} />
              </>
            )}
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
              <div className="table-wrapper" ref={tableWrapperRef}>
                <table className="school-table">
                  <thead>
                  <tr ref={headerRowRef}>
                    <th></th>
                    <th>First Name</th>
                    <th>Last Name</th>
                    <th>Email</th>
                    <th>Location</th>
                    {userRole === 'admin' && <th>School</th>}
                    <th>License</th>
                    <th className="edit-col">Edit</th>
                    <th className="assigned-col">Assigned Jobs</th>
                    <th className="placement-status-col">Placement Status</th>
                    <th className="placement-controls-col">Placement Controls</th>
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
                    <th>
                      <input
                        className="column-filter"
                        type="text"
                        value={locationFilter}
                        onChange={(e) => setLocationFilter(e.target.value)}
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
                    <th>
                      <select
                        className="column-filter"
                        value={licenseFilter}
                        onChange={(e) => setLicenseFilter(e.target.value)}
                      >
                        <option value="">All</option>
                        {licenses.map((l) => (
                          <option key={l.code} value={l.code}>
                            {l.label}
                          </option>
                        ))}
                      </select>
                    </th>
                    <th></th>
                    <th>
                      <input
                        className="column-filter"
                        type="number"
                        value={assignedFilter}
                        onChange={(e) => setAssignedFilter(e.target.value)}
                        placeholder="Filter"
                      />
                    </th>
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
                            <Tooltip
                              text={expandedRows[s.email] ? 'Collapse' : 'Expand'}
                              position="bottom"
                            >
                              <button
                                className="expand-toggle"
                                onClick={() => toggleRow(s.email, s.assigned_jobs)}
                                type="button"
                                title={expandedRows[s.email] ? 'Collapse' : 'Expand'}
                              >
                                {expandedRows[s.email] ? '–' : '+'}
                              </button>
                            </Tooltip>
                          </td>
                          <td>{s.first_name}</td>
                          <td>{s.last_name}</td>
                          <td>{s.email}</td>
                          <td>{[s.city, s.state].filter(Boolean).join(', ')}</td>
                          {userRole === 'admin' && <td>{s.institutional_code}</td>}
                          <td>{licenseLabel(s.license)}</td>
                          <td className="edit-col">
                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                              <Tooltip text="Edit" position="bottom">
                                <button
                                  onClick={() => handleEdit(s.email)}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    fontSize: '1.2rem',
                                  }}
                                >
                                  ✏️
                                </button>
                              </Tooltip>
                              {userRole === 'admin' && (
                                <Tooltip text="Delete Student" position="bottom">
                                  <button
                                    onClick={() => handleDelete(s.email)}
                                    style={{
                                      background: 'none',
                                      border: 'none',
                                      cursor: 'pointer',
                                      fontSize: '1.2rem',
                                      color: 'red',
                                    }}
                                  >
                                    🗑️
                                  </button>
                                </Tooltip>
                              )}
                            </div>
                          </td>
                          <td className="assigned-col">{assigned}</td>
                          <td className="placement-status-col">{placed > 0 ? '✅' : '❌'}</td>
                          <td className="placement-controls-col">
                            {assigned > 0 && placed === 0 && userRole !== 'admin' && (
                              <button onClick={() => handleMarkPlaced(s)}>
                                Mark as Placed
                              </button>
                            )}
                          </td>
                        </tr>
                        {expandedRows[s.email] && (
                          <tr
                            className={`job-subrow${expandedRows[s.email] === 'closing' ? ' closing' : ''}`}
                            key={`${s.email}-jobs`}
                          >
                            <td colSpan="100%">
                              <table className="job-subtable">
                                <thead>
                                  <tr>
                                    <th>Job Title</th>
                                    <th>Rate</th>
                                    <th>Source</th>
                                    <th>Job Description</th>
                                    <th>Status</th>
                                    <th>Recruiter Note</th>
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
                                        <td>{job.status}</td>
                                        <td>
                                          <button
                                            className="view-notes-btn"
                                            onClick={() =>
                                              setModalNotes({
                                                notes: job.notes || [],
                                                jobCode: job.job_code,
                                                studentEmail: s.email,
                                                canAdd:
                                                  isAdmin ||
                                                  (userRole === 'recruiter' &&
                                                    job.posted_by === decoded.sub &&
                                                    job.status === 'assigned'),
                                              })
                                            }
                                            type="button"
                                          >
                                            View Notes
                                            {job.notes && ` (${job.notes.length})`}
                                          </button>
                                        </td>
                                      </tr>
                                    ))
                                  ) : (
                                    <tr className="no-jobs-row">
                                      <td colSpan="6">No jobs assigned by recruiters.</td>
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
              </div>
            ) : (
              <p>You haven't created any student profiles.</p>
            )}
          </div>
        </div>
        )}
      </div>
      {modalNotes && (
        <NotesHistoryModal
          notes={modalNotes.notes}
          jobCode={modalNotes.jobCode}
          studentEmail={modalNotes.studentEmail}
          canAdd={modalNotes.canAdd}
          isAdmin={isAdmin}
          onClose={() => setModalNotes(null)}
        />
      )}
      </div>
    </div>
  );
}

export default StudentProfiles;
