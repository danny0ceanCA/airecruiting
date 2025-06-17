import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import './JobPosting.css';

function JobPosting() {
  const [formData, setFormData] = useState({
    job_title: '',
    job_description: '',
    desired_skills: '',
    job_code: '',
    source: '',
    rate_of_pay_range: ''
  });
  const [message, setMessage] = useState('');
  const [jobs, setJobs] = useState([]);
  const [search, setSearch] = useState('');
  const [matches, setMatches] = useState({});
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  const token = localStorage.getItem('token');

  const fetchJobs = async () => {
    try {
      const resp = await axios.get('http://localhost:8000/jobs', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setJobs(resp.data || []);
    } catch (err) {
      console.error('Error fetching jobs:', err);
      setJobs([]);
    }
  };

  useEffect(() => {
    if (token) {
      fetchJobs();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      await axios.post(
        'http://localhost:8000/jobs',
        {
          job_title: formData.job_title,
          job_description: formData.job_description,
          desired_skills: formData.desired_skills
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
          job_code: formData.job_code,
          source: formData.source,
          rate_of_pay_range: formData.rate_of_pay_range
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMessage('Job posted successfully!');
      setFormData({
        job_title: '',
        job_description: '',
        desired_skills: '',
        job_code: '',
        source: '',
        rate_of_pay_range: ''
      });
      fetchJobs();
    } catch (err) {
      console.error('Error posting job:', err);
    }
  };

  const handleMatch = async (code) => {
    try {
      const resp = await axios.post(
        'http://localhost:8000/match',
        { job_code: code },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMatches((prev) => ({ ...prev, [code]: resp.data.matches }));
    } catch (err) {
      console.error('Error matching job:', err);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const filteredJobs = jobs.filter((j) => {
    const q = search.toLowerCase();
    return (
      j.job_code.toLowerCase().includes(q) ||
      j.job_title.toLowerCase().includes(q) ||
      j.source.toLowerCase().includes(q)
    );
  });

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

      <form className="job-form" onSubmit={handleSubmit}>
        <h2>Post a Job</h2>
        <label htmlFor="job_title">Job Title</label>
        <input
          id="job_title"
          name="job_title"
          type="text"
          value={formData.job_title}
          onChange={handleChange}
        />
        <label htmlFor="job_description">Job Description</label>
        <textarea
          id="job_description"
          name="job_description"
          value={formData.job_description}
          onChange={handleChange}
        ></textarea>
        <label htmlFor="desired_skills">Desired Skills (comma separated)</label>
        <input
          id="desired_skills"
          name="desired_skills"
          type="text"
          value={formData.desired_skills}
          onChange={handleChange}
        />
        <label htmlFor="job_code">Job Code</label>
        <input
          id="job_code"
          name="job_code"
          type="text"
          value={formData.job_code}
          onChange={handleChange}
        />
        <label htmlFor="source">Source</label>
        <input
          id="source"
          name="source"
          type="text"
          value={formData.source}
          onChange={handleChange}
        />
        <label htmlFor="rate_of_pay_range">Rate of Pay Range</label>
        <input
          id="rate_of_pay_range"
          name="rate_of_pay_range"
          type="text"
          value={formData.rate_of_pay_range}
          onChange={handleChange}
        />
        <button type="submit">Submit</button>
        {message && <p className="message">{message}</p>}
      </form>

      <div className="jobs-section">
        <h2>Jobs</h2>
        <input
          className="search-input"
          type="text"
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <table className="jobs-table">
          <thead>
            <tr>
              <th>Job Code</th>
              <th>Title</th>
              <th>Source</th>
              <th>Rate</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredJobs.map((job) => (
              <React.Fragment key={job.job_code}>
                <tr>
                  <td>{job.job_code}</td>
                  <td>{job.job_title}</td>
                  <td>{job.source}</td>
                  <td>{job.rate_of_pay_range}</td>
                  <td>
                    <button onClick={() => handleMatch(job.job_code)}>Match</button>
                  </td>
                </tr>
                {matches[job.job_code] && (
                  <tr className="matches-row">
                    <td colSpan="5">
                      <table className="matches-table">
                        <thead>
                          <tr>
                            <th>First Name</th>
                            <th>Last Name</th>
                            <th>Email</th>
                            <th>Score</th>
                          </tr>
                        </thead>
                        <tbody>
                          {matches[job.job_code].map((m, idx) => (
                            <tr key={idx}>
                              <td>{m.first_name || m.name?.split(' ')[0]}</td>
                              <td>{m.last_name || m.name?.split(' ')[1]}</td>
                              <td>{m.email}</td>
                              <td>{m.score.toFixed(2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default JobPosting;
