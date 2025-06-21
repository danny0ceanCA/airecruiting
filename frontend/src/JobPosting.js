import React, { useEffect, useState } from 'react';
import { Link, useNavigate, Navigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import api from './api';
import './JobPosting.css';

function JobPosting() {
  const [formData, setFormData] = useState({
    job_title: '',
    job_description: '',
    desired_skills: '',
    source: '',
    rate_of_pay_range: ''
  });
  const [message, setMessage] = useState('');
  const [jobs, setJobs] = useState([]);
  const [codeFilter, setCodeFilter] = useState('');
  const [titleFilter, setTitleFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [expandedJob, setExpandedJob] = useState(null);
  const [selectedRows, setSelectedRows] = useState({});
  const [matches, setMatches] = useState({});
  const [expandedJobDetails, setExpandedJobDetails] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');
  const { role } = token ? jwtDecode(token) : {};
  if (role !== 'admin') return <Navigate to="/dashboard" />;

  const fetchJobs = async () => {
    try {
      const resp = await api.get('/jobs', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setJobs(resp.data.jobs || []);
    } catch (err) {
      console.error('Error fetching jobs:', err);
      setJobs([]);
    }
  };

  useEffect(() => {
    if (token) fetchJobs();
  }, []);

  useEffect(() => {
    if (expandedJob && !matches[expandedJob]) {
      handleMatch(expandedJob);
    }
  }, [expandedJob]);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const resp = await api.post('/jobs', {
        job_title: formData.job_title,
        job_description: formData.job_description,
        desired_skills: formData.desired_skills.split(',').map((s) => s.trim()).filter(Boolean),
        source: formData.source,
        rate_of_pay_range: formData.rate_of_pay_range
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMessage(`Job posted successfully! Job code: ${resp.data.job_code}`);
      setFormData({
        job_title: '', job_description: '', desired_skills: '', source: '', rate_of_pay_range: ''
      });
      fetchJobs();
    } catch (err) {
      console.error('Error posting job:', err);
    }
  };

  const handleMatch = async (code) => {
    try {
      const resp = await api.post('/match', { job_code: code }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const matchResults = resp.data.matches;
      setMatches((prev) => ({ ...prev, [code]: matchResults }));
    } catch (err) {
      console.error('Error matching job:', err);
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
      await api.post('/assign', {
        student_email: row.email,
        job_code: job.job_code
      }, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });
      setMatches((prev) => ({
        ...prev,
        [job.job_code]: prev[job.job_code].map((m) =>
          m.email === row.email ? { ...m, status: 'assigned' } : m
        )
      }));
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
    } catch (err) {
      console.error('Place failed', err);
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

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const matchFilter = (j) => {
    const codeMatch = j.job_code?.toLowerCase().includes(codeFilter.toLowerCase());
    const titleMatch = j.job_title?.toLowerCase().includes(titleFilter.toLowerCase());
    const sourceMatch = j.source?.toLowerCase().includes(sourceFilter.toLowerCase());
    return codeMatch && titleMatch && sourceMatch;
  };
  const filteredJobs = jobs.filter(matchFilter);

  return (
    <div className="job-posting-container">
      <div className="admin-menu">
        <button className="menu-button" onClick={() => setMenuOpen((o) => !o)}>
          Admin Menu
        </button>
        {menuOpen && (
          <div className="dropdown-menu">
            <Link to="/dashboard">Dashboard</Link>
            <Link to="/admin/pending">Pending Approvals</Link>
            <Link to="/students">Student Profiles</Link>
            <button onClick={handleLogout}>Logout</button>
          </div>
        )}
      </div>
      <div className="job-matching-layout">
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
            <div className="form-field">
              <label htmlFor="rate_of_pay_range">Rate of Pay Range</label>
              <input
                id="rate_of_pay_range"
                name="rate_of_pay_range"
                type="text"
                value={formData.rate_of_pay_range}
                onChange={handleChange}
              />
            </div>
            <button type="submit">Submit</button>
            {message && <p className="message">{message}</p>}
          </form>
        </div>

        <div className="posted-jobs-panel">
        <h2>Jobs</h2>
        <table className="job-table">
          <thead>
            <tr>
              <th></th>
              <th>Job Code</th>
              <th>Title</th>
              <th>Source</th>
              <th>Rate</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
            <tr className="filter-row">
              <th></th>
              <th><input className="column-filter" type="text" value={codeFilter} onChange={(e) => setCodeFilter(e.target.value)} placeholder="Filter" /></th>
              <th><input className="column-filter" type="text" value={titleFilter} onChange={(e) => setTitleFilter(e.target.value)} placeholder="Filter" /></th>
              <th><input className="column-filter" type="text" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} placeholder="Filter" /></th>
              <th colSpan="3"></th>
            </tr>
          </thead>
          <tbody>
            {filteredJobs.map((job) => (
              <React.Fragment key={job.job_code}>
                <tr>
                  <td>
                    <span
                      className="expand-toggle"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (expandedJob === job.job_code) {
                          setExpandedJob(null);
                          setExpandedJobDetails(null);
                        } else {
                          setExpandedJob(job.job_code);
                        }
                      }}
                    >
                      {expandedJob === job.job_code ? '–' : '+'}
                    </span>
                  </td>
                  <td>{job.job_code}</td>
                  <td
                    className={
                      expandedJobDetails === job.job_code && expandedJob === job.job_code
                        ? "highlight-cell"
                        : ""
                    }
                  >
                    <span
                      className="job-title-clickable"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (expandedJob === job.job_code) {
                          setExpandedJobDetails(
                            expandedJobDetails === job.job_code ? null : job.job_code
                          );
                        }
                      }}
                    >
                      {job.job_title}
                    </span>
                  </td>
                  <td>{job.source}</td>
                  <td>{job.rate_of_pay_range}</td>
                  <td className={expandedJob === job.job_code ? "highlight-cell" : ""}>
                    {job.placed_students?.length > 0 ? (
                      <span className="badge placed">Placed</span>
                    ) : job.assigned_students?.length > 0 ? (
                      <span
                        className="badge assigned"
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedJob(
                            expandedJob === job.job_code ? null : job.job_code
                          );
                        }}
                      >
                        Assigned
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <button onClick={() => setExpandedJob(expandedJob === job.job_code ? null : job.job_code)}>Match</button>
                  </td>
                </tr>
                {expandedJobDetails === job.job_code && expandedJob === job.job_code && (
                  <tr className="job-details-row">
                    <td colSpan="7">
                      <div className="job-description-panel">
                        <h3>{job.job_title}</h3>
                        <p>{job.job_description}</p>
                        {job.desired_skills && (
                          <p>
                            Skills: {Array.isArray(job.desired_skills) ? job.desired_skills.join(', ') : job.desired_skills}
                          </p>
                        )}
                        <p>Source: {job.source}</p>
                        <p>Rate of Pay: {job.rate_of_pay_range}</p>
                        <button>Edit</button>
                      </div>
                    </td>
                  </tr>
                )}
                {expandedJob === job.job_code && (
                  <tr className="match-table-row">
                    <td colSpan="7">
                      <button
                        disabled={(selectedRows[job.job_code]?.length || 0) === 0}
                        onClick={() => bulkAssign(job)}
                      >
                        Assign Selected ({selectedRows[job.job_code]?.length || 0})
                      </button>
                      {matches[job.job_code] && (
                        <table className="matches-table">
                          <thead>
                            <tr>
                              <th></th>
                              <th>Name</th>
                              <th>Email</th>
                              <th>Score</th>
                              <th>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {matches[job.job_code].map((row, idx) => {
                              const selectedCount = selectedRows[job.job_code]?.length || 0;
                              const checked = selectedRows[job.job_code]?.includes(row.email);
                              const disableCheckbox = row.status !== null || (selectedCount >= 3 && !checked);
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
                                  <td>{row.first_name || row.name?.split(' ')[0]} {row.last_name || row.name?.split(' ')[1]}</td>
                                  <td>{row.email}</td>
                                  <td>{row.score.toFixed(2)}</td>
                                  <td>
                                    {row.status === 'placed' ? (
                                      <span className="badge placed">Placed</span>
                                    ) : row.status === 'assigned' ? (
                                      <>
                                        <span className="badge assigned">Assigned</span>
                                        <button onClick={() => handlePlace(job, row)}>Place</button>
                                      </>
                                    ) : (
                                      <>
                                        <button onClick={() => handleAssign(job, row)}>Assign</button>
                                        <button onClick={() => handlePlace(job, row)}>Place</button>
                                      </>
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      </div>
    </div>
  );
}

export default JobPosting;
