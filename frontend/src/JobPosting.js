import React, { useEffect, useState, useRef } from 'react';
import { Navigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import api from './api';
import AdminMenu from './AdminMenu';
import loadGoogleMaps from './utils/loadGoogleMaps';
import './JobPosting.css';

function JobPosting() {
  const [formData, setFormData] = useState({
    job_title: '',
    job_description: '',
    desired_skills: '',
    source: '',
    min_pay: '',
    max_pay: '',
    city: '',
    state: '',
    lat: '',
    lng: ''
  });
  const [message, setMessage] = useState('');
  const [jobs, setJobs] = useState([]);
  const [codeFilter, setCodeFilter] = useState('');
  const [titleFilter, setTitleFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [expandedJob, setExpandedJob] = useState(null);
  const [activeSubtab, setActiveSubtab] = useState({}); // keyed by job_code
  const [selectedRows, setSelectedRows] = useState({});
  const [matches, setMatches] = useState({});
  const [loadingMatches, setLoadingMatches] = useState({});
  const [matchLoaded, setMatchLoaded] = useState({});
  const [matchPresence, setMatchPresence] = useState({});
  const [editMode, setEditMode] = useState({});
  const [editedJobs, setEditedJobs] = useState({});
  const [generatingResumes, setGeneratingResumes] = useState({});
  const [generatedResumes, setGeneratedResumes] = useState({});
  const [activeTab, setActiveTab] = useState('jobs');

  const locationRef = useRef(null);

  const initLocationAutocomplete = () => {
    if (locationRef.current && window.google) {
      const ac = new window.google.maps.places.Autocomplete(locationRef.current, { types: ['(cities)'] });
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
    loadGoogleMaps(initLocationAutocomplete);
  }, [activeTab]);

  const token = localStorage.getItem('token');
  const decoded = token ? jwtDecode(token) : {};
  const userRole = decoded?.role;
const { sub: email } = decoded;
const isRecruiter = userRole === 'recruiter';
const shouldRedirect = userRole !== 'admin' && userRole !== 'recruiter';


  const fetchJobs = async () => {
    try {
      const resp = await api.get('/jobs', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const allJobs = resp.data.jobs || [];
      const filtered = isRecruiter
        ? allJobs.filter((job) => job.posted_by === email)
        : allJobs;
      setJobs(filtered);
    } catch (err) {
      console.error('Error fetching jobs:', err);
      setJobs([]);
    }
  };

  const checkMatchFlags = async () => {
    const result = {};
    for (const job of jobs) {
      try {
        const resp = await api.get(`/has-match/${job.job_code}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        result[job.job_code] = resp.data.has_match;
      } catch {
        result[job.job_code] = false;
      }
    }
    setMatchPresence(result);
  };


  useEffect(() => {
  if (token) {
    fetchJobs();
  }
}, [token]);


  useEffect(() => {
  if (jobs.length > 0) {
    checkMatchFlags();
  }
}, [jobs]);


  useEffect(() => {
  const shouldLoad =
    expandedJob &&
    matchPresence[expandedJob] === true &&
    !matches[expandedJob];

  if (shouldLoad) {
    loadMatchResults(expandedJob);
  }
}, [expandedJob, matchPresence, matches]);

if (shouldRedirect) {
  return <Navigate to="/dashboard" />;
}

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    const min = parseFloat(formData.min_pay);
    const max = parseFloat(formData.max_pay);
    if (isNaN(min) || isNaN(max) || min <= 0 || max <= 0) {
      setMessage('Pay must be positive numbers');
      return;
    }
    if (min > max) {
      setMessage('Minimum pay cannot exceed maximum pay');
      return;
    }
    try {
      const payload = {
        job_title: formData.job_title,
        job_description: formData.job_description,
        desired_skills: formData.desired_skills.split(',').map((s) => s.trim()).filter(Boolean),
        min_pay: min,
        max_pay: max,
        city: formData.city,
        state: formData.state,
        lat: parseFloat(formData.lat || 0),
        lng: parseFloat(formData.lng || 0)
      };
      if (!isRecruiter) {
        payload.source = formData.source;
      }
      const resp = await api.post('/jobs', payload, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMessage(`Job posted successfully! Job code: ${resp.data.job_code}`);
      setFormData({
        job_title: '', job_description: '', desired_skills: '', source: '', min_pay: '', max_pay: '', city: '', state: '', lat: '', lng: ''
      });
      fetchJobs();
    } catch (err) {
      console.error('Error posting job:', err);
    }
  };

  const handleMatch = async (code) => {
    try {
      setLoadingMatches((prev) => ({ ...prev, [code]: true }));
      const resp = await api.post(
        '/match',
        { job_code: code },
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      const matchResults = resp.data.matches.map((m) => ({ ...m, status: null }));
      setMatches((prev) => ({ ...prev, [code]: matchResults }));
      setMatchPresence((prev) => ({ ...prev, [code]: true }));
    } catch (err) {
      console.error('Error matching job:', err);
    } finally {
      setLoadingMatches((prev) => ({ ...prev, [code]: false }));
    }
  };

  const handleRematch = async (code) => {
    try {
      setLoadingMatches((prev) => ({ ...prev, [code]: true }));
      const resp = await api.post(
        `/rematches/${code}`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const matchResults = resp.data.matches.map((m) => ({ ...m, status: null }));
      setMatches((prev) => ({ ...prev, [code]: matchResults }));
    } catch (err) {
      console.error('Error rematching job:', err);
    } finally {
      setLoadingMatches((prev) => ({ ...prev, [code]: false }));
    }
  };

  const loadMatchResults = async (code) => {
    try {
      const resp = await api.get(`/match/${code}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const matchResults = resp.data.matches.map((m) => ({
        ...m,
        status: m.status || null
      }));
      setMatches((prev) => ({ ...prev, [code]: matchResults }));
      setMatchLoaded((prev) => ({ ...prev, [code]: true }));
    } catch (err) {
      console.error(`Error loading stored matches for ${code}:`, err);
    }
  };

  const handleSelect = (jobCode, email) => (e) => {
    setSelectedRows((prev) => {
      const current = prev[jobCode] || [];
      if (e.target.checked) return { ...prev, [jobCode]: [...current, email] };
      return { ...prev, [jobCode]: current.filter((em) => em !== email) };
    });
  };

  const handleAssign = async (job, row) => {
    try {
      await api.post(
        '/assign',
        {
          student_email: row.email,
          job_code: job.job_code,
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        }
      );
      setMatches((prev) => ({
        ...prev,
        [job.job_code]: prev[job.job_code].map((m) =>
          m.email === row.email ? { ...m, status: 'assigned' } : m
        ),
      }));
      setJobs((prevJobs) =>
        prevJobs.map((j) =>
          j.job_code === job.job_code
            ? {
                ...j,
                assigned_students: [
                  ...(j.assigned_students || []),
                  row.email,
                ],
              }
            : j
        )
      );
    } catch (err) {
      console.error('Assign failed', err.response?.data || err.message);
    }
  };

  const handlePlace = async (job, row) => {
    try {
      await api.post('/place', {
        student_email: row.email,
        job_code: job.job_code
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMatches((prev) => ({
        ...prev,
        [job.job_code]: prev[job.job_code].map((m) =>
          m.email === row.email ? { ...m, status: 'placed' } : m
        )
      }));

      setJobs((prevJobs) =>
        prevJobs.map((j) =>
          j.job_code === job.job_code
            ? {
                ...j,
                placed_students: [...(j.placed_students || []), row.email],
                assigned_students: (j.assigned_students || []).filter(
                  (email) => email !== row.email
                )
              }
            : j
        )
      );
    } catch (err) {
      console.error('Place failed', err);
    }
  };

  const notifyInterest = async (jobCode, email) => {
    try {
      await api.post(
        '/notify-interest',
        { job_code: jobCode, student_email: email },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert('Candidate notified of interest');
    } catch (err) {
      console.error('Notification failed', err);
    }
  };

  const markNotInterested = async (jobCode, email) => {
    try {
      await api.post(
        '/not-interested',
        { job_code: jobCode, student_email: email },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMatches((prev) => ({
        ...prev,
        [jobCode]: (prev[jobCode] || []).filter((m) => m.email !== email)
      }));
    } catch (err) {
      console.error('Not interested call failed', err);
    }
  };

  const bulkAssign = async (job) => {
    const emails = selectedRows[job.job_code] || [];
    for (const email of emails) {
      try {
        await api.post('/assign', {
          student_email: email,
          job_code: job.job_code
        }, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setMatches((prev) => ({
          ...prev,
          [job.job_code]: prev[job.job_code].map((m) =>
            m.email === email ? { ...m, status: 'assigned' } : m
          )
        }));
      } catch (err) {
        console.error('Bulk assign failed', err);
      }
    }
    setSelectedRows((prev) => ({ ...prev, [job.job_code]: [] }));
  };

  const handleSave = async (job) => {
    try {
      await api.put(
        `/jobs/${job.job_code}`,
        editedJobs[job.job_code],
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert('Job updated!');
      fetchJobs();
      setEditMode((prev) => ({ ...prev, [job.job_code]: false }));
    } catch (err) {
      console.error('Update failed', err);
      alert('Failed to update job.');
    }
  };

  const handleDeleteJob = async (jobCode) => {
    if (
      !window.confirm(
        `Are you sure you want to delete job ${jobCode}? This cannot be undone.`
      )
    )
      return;

    try {
      await api.delete(`/jobs/${jobCode}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      alert("Job deleted successfully.");
      fetchJobs();
    } catch (err) {
      console.error("Failed to delete job", err);
      alert("Failed to delete the job.");
    }
  };

  const generateResume = async (email, jobCode) => {
    const key = `${jobCode}:${email}`;
    if (generatedResumes[key]) return;

    setGeneratingResumes((prev) => ({ ...prev, [key]: true }));

    try {
      const resp = await api.post(
        '/generate-resume',
        {
          student_email: email,
          job_code: jobCode,
        },
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      if (resp.data.status === 'success' || resp.data.status === 'exists') {
        console.log('Resume generation complete:', resp.data.message);
        setGeneratedResumes((prev) => ({ ...prev, [key]: true }));
      }
    } catch (err) {
      console.error('Resume generation error:', err);
    } finally {
      setGeneratingResumes((prev) => ({ ...prev, [key]: false }));
    }
  };

  const previewResume = async (email, jobCode) => {
    try {
      const resp = await api.post(
        '/generate-resume',
        { student_email: email, job_code: jobCode, preview: true },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const newWindow = window.open('', '_blank');
      if (newWindow) {
        newWindow.document.write(resp.data.html);
        newWindow.document.close();
      }
    } catch (err) {
      console.error('Preview resume error:', err);
    }
  };

  const viewResume = async (studentEmail, jobCode) => {
    try {
      const resp = await api.get(`/resume-html/${jobCode}/${studentEmail}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const newWindow = window.open('', '_blank');
      if (newWindow) {
        newWindow.document.write(resp.data);
        newWindow.document.close();
      }
    } catch (err) {
      console.error('Resume load failed', err);
      alert('Unable to load resume');
    }
  };


  const renderMatches = (job) => {
    const matchList = matches[job.job_code] || [];
    const unassignedMatches = matchList.filter(
      (m) => m.status !== 'assigned' && m.status !== 'placed'
    );
    return (
      <>
        {loadingMatches[job.job_code] && (
          <div className="loader-bar">Loading matches...</div>
        )}
        <button
          disabled={(selectedRows[job.job_code]?.length || 0) === 0}
          onClick={() => bulkAssign(job)}
        >
          Mark Selected as Interested ({selectedRows[job.job_code]?.length || 0})
        </button>
        <table className="matches-table">
          <thead>
            <tr>
              <th></th>
              <th>Name</th>
              <th>Score</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {matches[job.job_code] === undefined ? (
              <tr>
                <td colSpan="100%" className="match-prompt">
                  Press <strong>Match</strong> to find your candidates.
                </td>
              </tr>
            ) : (
              unassignedMatches.map((row, idx) => {
                const selectedCount = selectedRows[job.job_code]?.length || 0;
                const checked = selectedRows[job.job_code]?.includes(row.email);
                const disableCheckbox =
                  row.status !== null || (selectedCount >= 3 && !checked);
                return (
                  <tr key={idx}>
                    <td>
                      <input
                        type="checkbox"
                        disabled={disableCheckbox}
                        checked={checked || false}
                        onChange={handleSelect(job.job_code, row.email)}
                      />
                    </td>
                    <td>
                      {row.first_name || row.name?.split(' ')[0]}{' '}
                      {row.last_name || row.name?.split(' ')[1]}
                    </td>
                    <td>{row.score.toFixed(2)}</td>
                    <td>
                      {row.status === 'placed' ? (
                        <span className="badge placed inline">Placed</span>
                      ) : row.status === 'assigned' ? (
                        <>
                          <span className="badge assigned inline">Assigned</span>
                          {!isRecruiter && (
                            <button onClick={() => handlePlace(job, row)}>Place</button>
                          )}
                        </>
                      ) : (
                        <>
                          <button onClick={() => handleAssign(job, row)}>Interested</button>
                          <button onClick={() => markNotInterested(job.job_code, row.email)}>Not Interested</button>
                          {!isRecruiter && (
                            <button onClick={() => handlePlace(job, row)}>Place</button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </>
      );
  };

  const renderAssigned = (job) => {
    const matchList = matches[job.job_code] || [];
    const assignedMatches = matchList.filter((m) => m.status === 'assigned');
    return (
      <table className="matches-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Score</th>
            <th>Resume</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {assignedMatches.map((row, i) => (
            <tr key={i}>
              <td>{row.first_name || row.name?.split(' ')[0]} {row.last_name || row.name?.split(' ')[1]}</td>
              <td>{row.email}</td>
              <td>{row.score?.toFixed(2)}</td>
              <td>
                {generatingResumes[`${job.job_code}:${row.email}`] ? (
                  <span className="spinner">⏳</span>
                ) : generatedResumes[`${job.job_code}:${row.email}`] ? (
                  <button className="resume-icon-button" onClick={() => viewResume(row.email, job.job_code)}>
                    📥
                  </button>
                ) : (
                  <button onClick={() => generateResume(row.email, job.job_code)}>
                    Generate Resume
                  </button>
                )}
              </td>
              <td>
                <span className="badge assigned inline">Assigned</span>
                {isRecruiter && (
                  <button onClick={() => notifyInterest(job.job_code, row.email)}>Notify Candidate</button>
                )}
                {!isRecruiter && (
                  <button onClick={() => handlePlace(job, row)}>Place</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderPlaced = (job) => {
    const matchList = matches[job.job_code] || [];
    const placedMatches = matchList.filter((m) => m.status === 'placed');
    return (
      <table className="matches-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Score</th>
          </tr>
        </thead>
        <tbody>
          {placedMatches.map((row, i) => (
            <tr key={i}>
              <td>{row.name}</td>
              <td>{row.email}</td>
              <td>{row.score?.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const matchFilter = (j) => {
    const codeMatch = j.job_code?.toLowerCase().includes(codeFilter.toLowerCase());
    const titleMatch = j.job_title?.toLowerCase().includes(titleFilter.toLowerCase());
    const sourceMatch = j.source?.toLowerCase().includes(sourceFilter.toLowerCase());
    return codeMatch && titleMatch && sourceMatch;
  };
  const filteredJobs = jobs.filter(matchFilter);

  return (
    <div className="job-posting-container job-matching-module">
      <AdminMenu>
        {userRole === "admin" && (
          <button
            className="admin-reset-button"
            onClick={async () => {
              if (
                window.confirm(
                  "Are you sure you want to delete ALL jobs and match data?"
                )
              ) {
                try {
                  const resp = await api.delete("/admin/reset-jobs", {
                    headers: { Authorization: `Bearer ${token}` },
                  });
                  alert(resp.data.message);
                  fetchJobs();
                } catch (err) {
                  console.error("Reset failed:", err);
                  alert("Failed to reset jobs.");
                }
              }
            }}
          >
            🧨 Reset All Jobs
          </button>
        )}
      </AdminMenu>
      <div className="tab-bar">
        <button
          className={`tab ${activeTab === 'jobs' ? 'active' : ''}`}
          onClick={() => setActiveTab('jobs')}
        >
          Jobs
        </button>
        <button
          className={`tab ${activeTab === 'post' ? 'active' : ''}`}
          onClick={() => setActiveTab('post')}
        >
          Post a Job
        </button>
      </div>
      <div className="tab-content">
        {activeTab === 'post' && (
          <div className="post-job-panel">
            <form onSubmit={handleSubmit} className="post-job-form">
              <h2>Post a Job</h2>
              <div className="form-field">
                <label htmlFor="job_title">Job Title</label>
                <input
                  id="job_title"
                  name="job_title"
                  type="text"
                  value={formData.job_title}
                  onChange={handleChange}
                />
              </div>
              <div className="form-field">
                <label htmlFor="job_description">Job Description</label>
                <textarea
                  id="job_description"
                  name="job_description"
                  value={formData.job_description}
                  onChange={handleChange}
                ></textarea>
              </div>
              <div className="form-field">
                <label htmlFor="desired_skills">Desired Skills (comma separated)</label>
                <input
                  id="desired_skills"
                  name="desired_skills"
                  type="text"
                  value={formData.desired_skills}
                  onChange={handleChange}
                />
              </div>
              {!isRecruiter && (
                <div className="form-field">
                  <label htmlFor="source">Source</label>
                  <input
                    id="source"
                    name="source"
                    type="text"
                    value={formData.source}
                    onChange={handleChange}
                  />
                </div>
              )}
              <div className="form-field">
                <label htmlFor="min_pay">Minimum Pay</label>
                <input
                  id="min_pay"
                  name="min_pay"
                  type="number"
                  value={formData.min_pay}
                  onChange={handleChange}
                />
              </div>
              <div className="form-field">
                <label htmlFor="max_pay">Maximum Pay</label>
                <input
                  id="max_pay"
                  name="max_pay"
                  type="number"
                  value={formData.max_pay}
                  onChange={handleChange}
                />
              </div>
              <div className="form-field">
                <label htmlFor="city">City</label>
                <input
                  id="city"
                  name="city"
                  type="text"
                  value={formData.city}
                  onChange={handleChange}
                  ref={locationRef}
                />
              </div>
              <div className="form-field">
                <label htmlFor="state">State</label>
                <input
                  id="state"
                  name="state"
                  type="text"
                  value={formData.state}
                  onChange={handleChange}
                  readOnly
                />
              </div>
              <input type="hidden" id="lat" name="lat" value={formData.lat} readOnly />
              <input type="hidden" id="lng" name="lng" value={formData.lng} readOnly />
              <button type="submit">Submit</button>
              {message && <p className="message">{message}</p>}
            </form>
          </div>
        )}

        {activeTab === 'jobs' && (
          <div className="posted-jobs-panel">
            <table className="job-table">
            <thead>
              <tr>
                <th></th>
                <th>Job Code</th>
              <th>Title</th>
              <th>Source</th>
              <th>Pay Range</th>
              <th>Assigned</th>
              {!isRecruiter && <th>Placed</th>}
              <th>Action</th>
            </tr>
            <tr className="filter-row">
              <th></th>
              <th><input className="column-filter" type="text" value={codeFilter} onChange={(e) => setCodeFilter(e.target.value)} placeholder="Filter" /></th>
              <th><input className="column-filter" type="text" value={titleFilter} onChange={(e) => setTitleFilter(e.target.value)} placeholder="Filter" /></th>
              <th><input className="column-filter" type="text" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} placeholder="Filter" /></th>
              <th colSpan={!isRecruiter ? 4 : 3}></th>
            </tr>
          </thead>
          <tbody>
            {filteredJobs.map((job) => (
              <React.Fragment key={job.job_code}>
                <tr>
                  <td>
                    <button
                      type="button"
                      className="expand-toggle"
                      onClick={(e) => {
                        e.stopPropagation();
                        const isExpanded = expandedJob === job.job_code;
                        setExpandedJob(isExpanded ? null : job.job_code);
                        if (!isExpanded) {
                          setActiveSubtab((prev) => ({
                            ...prev,
                            [job.job_code]: 'matches',
                          }));
                        }
                      }}
                    >
                      {expandedJob === job.job_code ? '–' : '+'}
                    </button>
                  </td>
                  <td>{job.job_code}</td>
                  <td
                    className={
                      activeSubtab[job.job_code] === 'details' && expandedJob === job.job_code
                        ? "highlight-cell"
                        : ""
                    }
                  >
                    <span
                      className="job-title-clickable"
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveSubtab((prev) => ({ ...prev, [job.job_code]: 'details' }));
                      }}
                    >
                      {job.job_title}
                    </span>
                  </td>
                  <td>{job.source}</td>
                  <td>
                    {job.min_pay !== undefined && job.max_pay !== undefined
                      ? `${job.min_pay} - ${job.max_pay}`
                      : ''}
                  </td>
                  <td className="status-cell">
                    {job.assigned_students?.length > 0 && (
                      <span
                        className="badge assigned"
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedJob(job.job_code);
                          setActiveSubtab((prev) => ({ ...prev, [job.job_code]: 'assigned' }));
                        }}
                      >
                        {job.assigned_students.length}
                      </span>
                    )}
                  </td>
                  {!isRecruiter && (
                    <td className="status-cell">
                      {job.placed_students?.length > 0 && (
                        <span
                          className="badge placed"
                          onClick={(e) => {
                            e.stopPropagation();
                            setExpandedJob(job.job_code);
                            setActiveSubtab((prev) => ({
                              ...prev,
                              [job.job_code]: "placed",
                            }));
                          }}
                        >
                          {job.placed_students.length}
                        </span>
                      )}
                    </td>
                  )}
                  <td>
                    {(() => {
                      const hasMatchInRedis = matchPresence[job.job_code] === true;

                      return hasMatchInRedis ? (
                        <>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedJob(job.job_code);
                              setActiveSubtab((prev) => ({
                                ...prev,
                                [job.job_code]: 'matches',
                              }));
                            }}
                          >
                            View Matches
                          </button>
                          <button onClick={() => handleRematch(job.job_code)}>
                            Match Again
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleMatch(job.job_code);
                            setExpandedJob(job.job_code);
                            setActiveSubtab((prev) => ({
                              ...prev,
                              [job.job_code]: 'matches',
                            }));
                          }}
                        >
                          Match
                        </button>
                      );
                    })()}
                  </td>
                </tr>
                {expandedJob === job.job_code && (
                  activeSubtab[job.job_code] === 'details' ? (
                    <tr className="job-details-row">
                      <td colSpan={!isRecruiter ? 8 : 7}>
                        <div className="job-description-panel">
                          <h3>{job.job_title}</h3>
                          {editMode[job.job_code] ? (
                            <div className="edit-job-form">
                              <div className="form-row">
                                <label>Description</label>
                                <textarea
                                  value={editedJobs[job.job_code]?.job_description || job.job_description}
                                  onChange={(e) =>
                                    setEditedJobs((prev) => ({
                                      ...prev,
                                      [job.job_code]: {
                                        ...prev[job.job_code],
                                        job_description: e.target.value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="form-row">
                                <label>Skills</label>
                                <input
                                  type="text"
                                  placeholder="Comma separated"
                                  value={editedJobs[job.job_code]?.desired_skills || (Array.isArray(job.desired_skills) ? job.desired_skills.join(', ') : job.desired_skills) || ""}
                                  onChange={(e) =>
                                    setEditedJobs((prev) => ({
                                      ...prev,
                                      [job.job_code]: {
                                        ...prev[job.job_code],
                                        desired_skills: e.target.value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="form-row">
                                <label>Source</label>
                                <input
                                  type="text"
                                  value={editedJobs[job.job_code]?.source || job.source}
                                  onChange={(e) =>
                                    setEditedJobs((prev) => ({
                                      ...prev,
                                      [job.job_code]: {
                                        ...prev[job.job_code],
                                        source: e.target.value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="form-row">
                                <label>Minimum Pay</label>
                                <input
                                  type="number"
                                  value={editedJobs[job.job_code]?.min_pay ?? job.min_pay}
                                  onChange={(e) =>
                                    setEditedJobs((prev) => ({
                                      ...prev,
                                      [job.job_code]: {
                                        ...prev[job.job_code],
                                        min_pay: e.target.value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="form-row">
                                <label>Maximum Pay</label>
                                <input
                                  type="number"
                                  value={editedJobs[job.job_code]?.max_pay ?? job.max_pay}
                                  onChange={(e) =>
                                    setEditedJobs((prev) => ({
                                      ...prev,
                                      [job.job_code]: {
                                        ...prev[job.job_code],
                                        max_pay: e.target.value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="edit-job-buttons">
                                <button onClick={() => setEditMode((prev) => ({ ...prev, [job.job_code]: false }))}>Cancel</button>
                                <button onClick={() => handleSave(job)}>Save</button>
                              </div>
                            </div>
                          ) : (
                            <>
                              <p>{job.job_description}</p>
                              {job.desired_skills && (
                                <p>
                                  Skills: {Array.isArray(job.desired_skills) ? job.desired_skills.join(', ') : job.desired_skills}
                                </p>
                              )}
                              <p>Source: {job.source}</p>
                              <p>
                                Pay Range: {job.min_pay} - {job.max_pay}
                              </p>
                              {(userRole === 'admin' || job.posted_by === email) && (
                                <button
                                  onClick={() =>
                                    setEditMode((prev) => ({
                                      ...prev,
                                      [job.job_code]: true,
                                    }))
                                  }
                                >
                                  Edit
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    <tr className="match-table-row">
                      <td colSpan={!isRecruiter ? 8 : 7}>
                        {activeSubtab[job.job_code] === 'matches' && renderMatches(job)}
                        {activeSubtab[job.job_code] === 'assigned' && renderAssigned(job)}
                        {activeSubtab[job.job_code] === 'placed' && renderPlaced(job)}
                        {userRole === 'admin' && (
                          <div style={{ marginTop: '12px' }}>
                            <button
                              onClick={() => handleDeleteJob(job.job_code)}
                              style={{
                                backgroundColor: 'transparent',
                                border: '1px solid red',
                                color: 'red',
                                padding: '6px 12px',
                                cursor: 'pointer',
                                borderRadius: '4px'
                              }}
                            >
                              🗑️ Delete Job
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                )}
              </React.Fragment>
              ))}
          </tbody>
        </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default JobPosting;
