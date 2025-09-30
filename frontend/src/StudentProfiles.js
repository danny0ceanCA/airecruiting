import React, { useState, useEffect, useRef, useMemo, useCallback, lazy, Suspense } from 'react';
import api, { getAccessToken, getRefreshToken } from './api';
import { useNavigate } from 'react-router-dom';

import AdminMenu from './AdminMenu';
import jwt_decode from 'jwt-decode';
import './StudentProfiles.css';
import './Tour.css';
import Tooltip from './components/Tooltip';

const Joyride = lazy(() => import('react-joyride'));
const NotesHistoryModal = lazy(() => import('./NotesHistoryModal'));
const StudentForm = lazy(() => import('./StudentForm'));

function StudentProfiles() {
  const [licenses, setLicenses] = useState([]);
  const licenseLabel = (code) => {
    const l = licenses.find((x) => x.code === code);
    return l ? l.label : code;
  };
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
      target: '.student-form',
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
  const [nextCursor, setNextCursor] = useState(null);
  const [firstNameFilter, setFirstNameFilter] = useState('');
  const [lastNameFilter, setLastNameFilter] = useState('');
  const [emailFilter, setEmailFilter] = useState('');
  const [locationFilter, setLocationFilter] = useState('');
  const [codeFilter, setCodeFilter] = useState('');
  const [licenseFilter, setLicenseFilter] = useState('');
  const [placementFilter, setPlacementFilter] = useState('');
  const [editingEmail, setEditingEmail] = useState('');
  const [editingStudent, setEditingStudent] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const [activeTab, setActiveTab] = useState('students');

  const [jobDescriptionStatus, setJobDescriptionStatus] = useState({});

  const [expandedRows, setExpandedRows] = useState({});
  const [modalNotes, setModalNotes] = useState(null);
  const [hoveredJob, setHoveredJob] = useState(null);
  const hoverTimer = useRef(null);
  const [jobsByEmail, setJobsByEmail] = useState({});
  const [loadingJobs, setLoadingJobs] = useState({});
  const [jobStatsByEmail, setJobStatsByEmail] = useState({});
  const [jobAnalytics, setJobAnalytics] = useState([]);
  const [jobAnalyticsLoading, setJobAnalyticsLoading] = useState(false);
  const [jobAnalyticsError, setJobAnalyticsError] = useState('');
  const [jobAnalyticsLoaded, setJobAnalyticsLoaded] = useState(false);
  const [expandedAnalyticsJob, setExpandedAnalyticsJob] = useState(null);

  const mergeStudents = (list) => {
    const map = new Map();
    list.forEach((s) => {
      if (s && s.email) {
        map.set(s.email, { ...map.get(s.email), ...s });
      }
    });
    return Array.from(map.values());
  };

  const showTrackingPopover = (job, position) => {
    setHoveredJob({ job, position });

  };

  const handleJobEnter = (job, event) => {
    if ('ontouchstart' in window) return;
    const { clientX, clientY } = event;
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(
      () => showTrackingPopover(job, { top: clientY, left: clientX }),
      2000
    );
  };

  const handleJobLeave = () => {
    clearTimeout(hoverTimer.current);
    setHoveredJob(null);
  };

  const handleJobClick = (job, event) => {
    event.stopPropagation();
    clearTimeout(hoverTimer.current);
    const { clientX, clientY } = event;
    if (hoveredJob && hoveredJob.job.job_code === job.job_code) {
      setHoveredJob(null);
    } else {
      showTrackingPopover(job, { top: clientY, left: clientX });
    }
  };

  const formatDate = (value) =>
    value ? new Date(value).toLocaleString() : '—';

  const handleTourCallback = (data) => {
    const { status, type } = data;
    if (status === 'finished' || status === 'skipped') {
      localStorage.setItem('studentTourSeen', 'true');
      setShowTour(false);
    }
  };

  const tableWrapperRef = useRef(null);
  const headerRowRef = useRef(null);

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
  const token = getAccessToken();
  let decoded = {};
  try {
    decoded = token ? jwt_decode(token) : {};
  } catch (err) {
    decoded = {};
  }
  const userRole = decoded?.role;
  const isAdmin = userRole === 'admin' || userRole === 'junior_admin';
  const canViewJobAnalytics =
    isAdmin || userRole === 'career' || userRole === 'career_director';

  const loadJobAnalytics = useCallback(async () => {
    if (!token) return;
    setJobAnalyticsLoading(true);
    setJobAnalyticsError('');
    try {
      const resp = await api.get('/job-analytics', {
        headers: { Authorization: `Bearer ${token}` },
      });
      setJobAnalytics(resp.data?.jobs || []);
    } catch (err) {
      const message =
        err?.response?.data?.detail || err?.message || 'Failed to load job analytics';
      setJobAnalyticsError(message);
    } finally {
      setJobAnalyticsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (activeTab === 'analytics' && canViewJobAnalytics && !jobAnalyticsLoaded) {
      loadJobAnalytics();
      setJobAnalyticsLoaded(true);
    }
  }, [activeTab, canViewJobAnalytics, jobAnalyticsLoaded, loadJobAnalytics]);

  const fetchStudents = async (cursor = null) => {
    setIsLoading(true);
    const start = performance.now();
    try {
      const endpoint =
        userRole === 'admin' || userRole === 'junior_admin'
          ? '/students/all'
          : '/students/by-school';
      const resp = await api.get(endpoint, {
        params: { limit: 50, cursor },
        headers: { Authorization: `Bearer ${token}` },
      });
      const incoming = resp.data?.students || [];
      setSchoolStudents((prev) => mergeStudents([...prev, ...incoming]));
      setNextCursor(resp.data?.next_cursor || null);
    } catch (err) {
      if (err.response && err.response.status === 401) {
        navigate('/login');
      } else {
        console.error('Failed to fetch students:', err);
        setToast('Failed to load students. Please try again later.');
        setTimeout(() => setToast(''), 3000);
      }
    } finally {
      const duration = performance.now() - start;
      setIsLoading(false);
      setTimeout(() => {
        try {
          const p = api.post(
            '/metrics/student-load-time',
            { role: decoded.role, duration },
            { headers: { Authorization: `Bearer ${getAccessToken()}` } }
          );
          if (p && p.catch) p.catch(() => {});
        } catch (e) {
          /* ignore */
        }
      }, 0);
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
    const refreshToken = getRefreshToken();
    if (!token && !refreshToken) {
      navigate('/login');
      return;
    }
    fetchLicenses();
    fetchStudents();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!token) return;

    const controller = new AbortController();

    const refreshStudents = async () => {
      try {
        const response = await fetch('/students/all?limit=50', {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${token}`,
          },
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`Failed to fetch students: ${response.status}`);
        }

        const data = await response.json();
        const incoming = Array.isArray(data?.students)
          ? data.students
          : Array.isArray(data)
            ? data
            : [];

        if (incoming.length) {
          setSchoolStudents((prev) => mergeStudents([...prev, ...incoming]));
        }
      } catch (err) {
        if (err.name === 'AbortError') return;
        console.error('Failed to refresh students:', err);
      }
    };

    refreshStudents();

    return () => controller.abort();
  }, [token]);

  const toggleRow = (email) => {
    setExpandedRows((prev) => {
      const state = prev[email];
      const isOpen = state === 'open' || state === 'opening';
      if (!isOpen) {
        if (!jobStatsByEmail[email]) {
          api
            .get(`/students/${email}/job-stats`, {
              headers: { Authorization: `Bearer ${token}` },
            })
            .then((resp) =>
              setJobStatsByEmail((p) => ({ ...p, [email]: resp.data || {} }))
            )
            .catch((err) => console.error('Failed to fetch job stats', err));
        }
        if (!jobsByEmail[email]) {
          setLoadingJobs((l) => ({ ...l, [email]: true }));
          api
            .get(`/students/${email}/jobs`, {
              headers: { Authorization: `Bearer ${token}` },
            })
            .then((resp) => {
              const jobs = resp.data?.jobs || [];
              setJobsByEmail((p) => ({ ...p, [email]: jobs }));
              jobs.forEach((job) => fetchJobDescriptionStatus(email, job.job_code));
            })
            .catch((err) => console.error('Failed to fetch jobs', err))
            .finally(() =>
              setLoadingJobs((l) => ({ ...l, [email]: false }))
            );
        } else {
          jobsByEmail[email].forEach((job) =>
            fetchJobDescriptionStatus(email, job.job_code)
          );
        }
        return { ...prev, [email]: 'opening' };
      } else {
        setTimeout(() => {
          setExpandedRows((cur) => {
            const updated = { ...cur };
            delete updated[email];
            return updated;
          });
        }, 300);
        return { ...prev, [email]: 'closing' };
      }
    });

    requestAnimationFrame(() => {
      setExpandedRows((prev) =>
        prev[email] === 'opening' ? { ...prev, [email]: 'open' } : prev
      );
    });
  };

  const handleEdit = (email) => {
    const student = schoolStudents.find((s) => s.email === email);
    if (student) {
      const editData = {
        ...student,
        skills: Array.isArray(student.skills)
          ? student.skills.join(', ')
          : student.skills || '',
        interests: Array.isArray(student.interests)
          ? student.interests.join(', ')
          : student.interests || ''
      };
      setEditingStudent(editData);
      setEditingEmail(student.email);
      setDrawerOpen(true);
    }
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    setEditingStudent(null);
    setEditingEmail('');
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

  const resendJobDescription = async (jobCode, studentEmail) => {
    try {
      await api.post(
        '/notify-interest',
        { job_code: jobCode, student_email: studentEmail },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert('Job description resent');
      const [jobsResp, statsResp] = await Promise.all([
        api.get(`/students/${studentEmail}/jobs`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        api.get(`/students/${studentEmail}/job-stats`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);
      const jobs = jobsResp.data?.jobs || [];
      setJobsByEmail((p) => ({ ...p, [studentEmail]: jobs }));
      setJobStatsByEmail((p) => ({ ...p, [studentEmail]: statsResp.data || {} }));

      // If the analytics pop-over is open for this job, refresh it with the
      // latest data so the email tracking numbers update immediately.
      if (
        hoveredJob &&
        hoveredJob.job.job_code === jobCode &&
        hoveredJob.job.student_email === studentEmail
      ) {
        const updated = jobs.find((j) => j.job_code === jobCode);
        if (updated) {
          setHoveredJob({ job: updated, position: hoveredJob.position });
        }
      }
      await fetchJobDescriptionStatus(studentEmail, jobCode);
    } catch (err) {
      console.error('Notification failed', err);
    }
  };


  const handleCreate = async (data) => {
    setIsSaving(true);
    try {
      await api.post('/students', data, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      setToast('Student profile submitted!');
      setTimeout(() => setToast(''), 3000);
      fetchStudents();
      return true;
    } catch (err) {
      console.error('Submission failed:', err);
      setToast('Submission failed. Please check all required fields.');
      setTimeout(() => setToast(''), 3000);
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const handleUpdate = async (data) => {
    setIsSaving(true);
    try {
      await api.put(`/students/${editingEmail}`, data, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      setToast('Student profile updated!');
      setTimeout(() => setToast(''), 3000);
      fetchStudents();
      closeDrawer();
      return true;
    } catch (err) {
      console.error('Submission failed:', err);
      setToast('Submission failed. Please check all required fields.');
      setTimeout(() => setToast(''), 3000);
      return false;
    } finally {
      setIsSaving(false);
    }
  };


  const filteredStudents = useMemo(() => {
    return schoolStudents.filter((s) => {
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
        userRole !== 'admin' && userRole !== 'junior_admin'
          ? true
          : (s.institutional_code || '')
              .toLowerCase()
              .includes(codeFilter.toLowerCase());
      const licenseMatch =
        !licenseFilter || (s.license || '').toLowerCase() === licenseFilter.toLowerCase();
      const stats = jobStatsByEmail[s.email];
      const placed = stats
        ? stats.placed?.length || 0
        : Array.isArray(s.placed_jobs)
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
        placementMatch
      );
    });
  }, [
    schoolStudents,
    firstNameFilter,
    lastNameFilter,
    emailFilter,
    locationFilter,
    codeFilter,
    licenseFilter,
    placementFilter,
    userRole,
    jobStatsByEmail,
  ]);

  return (

    <div
      className="glass-panel"
      style={{ borderRadius: '1.25rem', overflow: 'hidden', width: '100%' }}
    >
      <div className="profiles-container">
        {showTour && (
          <Suspense fallback={null}>
            <Joyride
              steps={tourSteps}
              continuous
              showSkipButton
              showProgress
              callback={handleTourCallback}
              styles={{ options: { zIndex: 10000 } }}
            />
          </Suspense>
        )}
        <AdminMenu>
        {isAdmin && (
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
        <div className="tabs">
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
          {canViewJobAnalytics && (
            <button
              className={`tab analytics-tab ${activeTab === 'analytics' ? 'active' : ''}`}
              onClick={() => setActiveTab('analytics')}
            >
              Job Analytics
            </button>
          )}
        </div>
        {!isLoading && (
          <div className="student-count" data-testid="student-count">
            Student Profiles: <span className="count-number">{schoolStudents.length}</span>
          </div>
        )}
      </div>

      <div className="tab-content">
        {activeTab === 'new' && (
          <div className="form-panel">
            <Suspense fallback={<div>Loading...</div>}>
              <StudentForm
                title="New Student Profile"
                licenses={licenses}
                onSubmit={handleCreate}
                isSaving={isSaving}
              />
            </Suspense>
          </div>
        )}
        {activeTab === 'analytics' && canViewJobAnalytics && (
          <div className="job-analytics-panel">
            <div className="blast-history">
              <div className="blast-history-header">
                <h2>Job Analytics</h2>
                <button
                  type="button"
                  onClick={loadJobAnalytics}
                  disabled={jobAnalyticsLoading}
                  className="blast-history-refresh"
                >
                  {jobAnalyticsLoading ? 'Refreshing…' : 'Refresh'}
                </button>
              </div>
              {jobAnalyticsError && (
                <div className="blast-error blast-history-error">{jobAnalyticsError}</div>
              )}
              <div className="blast-history-table-wrapper">
                {jobAnalyticsLoading && jobAnalytics.length === 0 ? (
                  <div className="blast-history-loading">Loading job analytics…</div>
                ) : jobAnalytics.length === 0 ? (
                  <div className="blast-history-empty">No job analytics available yet.</div>
                ) : (
                  <table className="blast-history-table job-analytics-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>Job Code</th>
                        <th>Title</th>
                        <th>Assigned</th>
                        <th>Placed</th>
                        <th>Rejected</th>
                        <th>Uninterested</th>
                        <th>Emails Sent</th>
                        <th>Opened</th>
                        <th>Clicked</th>
                        <th>Open Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {jobAnalytics.map((job) => {
                        const isExpanded = expandedAnalyticsJob === job.job_code;
                        const openRate =
                          job.email_sent_count > 0
                            ? `${Math.round(
                                (job.opened_count / job.email_sent_count) * 100
                              )}%`
                            : '—';
                        return (
                          <React.Fragment key={job.job_code || job.job_title}>
                            <tr className="blast-row">
                              <td className="blast-expand-cell">
                                <button
                                  type="button"
                                  className="expand-toggle"
                                  onClick={() =>
                                    setExpandedAnalyticsJob(
                                      isExpanded ? null : job.job_code
                                    )
                                  }
                                  title={isExpanded ? 'Collapse' : 'Expand'}
                                >
                                  {isExpanded ? '–' : '+'}
                                </button>
                              </td>
                              <td>{job.job_code || '—'}</td>
                              <td className="job-analytics-job">
                                <div className="job-analytics-job-title">{job.job_title || '—'}</div>
                                {job.source && (
                                  <div className="job-analytics-job-meta">Source: {job.source}</div>
                                )}
                              </td>
                              <td className="metric-cell">{job.assigned_count ?? 0}</td>
                              <td className="metric-cell">{job.placed_count ?? 0}</td>
                              <td className="metric-cell">{job.rejected_count ?? 0}</td>
                              <td className="metric-cell">{job.uninterested_count ?? 0}</td>
                              <td className="metric-cell">{job.email_sent_count ?? 0}</td>
                              <td className="metric-cell">{job.opened_count ?? 0}</td>
                              <td className="metric-cell">{job.clicked_count ?? 0}</td>
                              <td className="metric-cell">{openRate}</td>
                            </tr>
                            {isExpanded && (
                              <tr className="blast-detail-row">
                                <td colSpan={11}>
                                  <div className="blast-detail">
                                    <div className="blast-summary-grid">
                                      <div>
                                        <strong>Assigned:</strong> {job.assigned_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Placed:</strong> {job.placed_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Rejected:</strong> {job.rejected_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Uninterested:</strong> {job.uninterested_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Emails Sent:</strong> {job.email_sent_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Opened:</strong> {job.opened_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Clicked:</strong> {job.clicked_count ?? 0}
                                      </div>
                                      <div>
                                        <strong>Open Rate:</strong> {openRate}
                                      </div>
                                    </div>
                                    <div className="blast-detail-filters job-analytics-meta">
                                      <div>
                                        <strong>Job Title:</strong> {job.job_title || '—'}
                                      </div>
                                      <div>
                                        <strong>Job Code:</strong> {job.job_code || '—'}
                                      </div>
                                      <div>
                                        <strong>Source:</strong> {job.source || '—'}
                                      </div>
                                      <div>
                                        <strong>Last Updated:</strong> {formatDate(job.timestamp)}
                                      </div>
                                    </div>
                                    <div className="blast-recipient-table-wrapper">
                                      {job.students?.length ? (
                                        <table className="blast-recipient-table">
                                          <thead>
                                            <tr>
                                              <th>Student</th>
                                              <th>Status</th>
                                              <th>Email Sent</th>
                                              <th>First Open</th>
                                              <th>Clicked</th>
                                            </tr>
                                          </thead>
                                          <tbody>
                                            {job.students.map((student) => {
                                              const fullName = [
                                                student.first_name,
                                                student.last_name,
                                              ]
                                                .filter(Boolean)
                                                .join(' ');
                                              const statusLabel = student.status
                                                ? student.status.charAt(0).toUpperCase() +
                                                  student.status.slice(1)
                                                : '—';
                                              return (
                                                <tr key={student.email}>
                                                  <td>
                                                    <div className="job-analytics-student-name">
                                                      {fullName || student.email}
                                                    </div>
                                                    <div className="job-analytics-student-email">
                                                      {student.email}
                                                    </div>
                                                  </td>
                                                  <td>{statusLabel}</td>
                                                  <td>{formatDate(student.email_sent)}</td>
                                                  <td>{formatDate(student.first_open)}</td>
                                                  <td>{student.clicked ? 'Yes' : 'No'}</td>
                                                </tr>
                                              );
                                            })}
                                          </tbody>
                                        </table>
                                      ) : (
                                        <div className="blast-history-empty">
                                          No student analytics available.
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
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
              <>
              <div className="table-wrapper" ref={tableWrapperRef}>
                <table className="school-table">
                  <thead>
                  <tr ref={headerRowRef}>
                    <th></th>
                    <th>First Name</th>
                    <th>Last Name</th>
                    <th>Email</th>
                    <th>Location</th>
                    {isAdmin && <th>School</th>}
                    <th>License</th>
                    <th className="edit-col">Edit</th>
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
                    {isAdmin && (
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
                    const stats = jobStatsByEmail[s.email];
                    const assigned = stats
                      ? (stats.assigned?.length || 0) +
                        (stats.placed?.length || 0) +
                        (stats.rejected?.length || 0) +
                        (stats.uninterested?.length || 0)
                      : 0;
                    const placed = stats
                      ? stats.placed?.length || 0
                      : Array.isArray(s.placed_jobs)
                      ? s.placed_jobs.length
                      : s.placed_jobs || 0;
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
                                onClick={() => toggleRow(s.email)}
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
                          {isAdmin && <td>{s.institutional_code}</td>}
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
                              {isAdmin && (
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
                          <td className="placement-status-col">{placed > 0 ? '✅' : '❌'}</td>
                          <td className="placement-controls-col">
                            {assigned > 0 && placed === 0 && userRole !== 'admin' && userRole !== 'junior_admin' && (
                              <button onClick={() => handleMarkPlaced(s)}>
                                Mark as Placed
                              </button>
                            )}
                          </td>
                        </tr>
                        {expandedRows[s.email] && (
                          <tr
                            className={`job-subrow ${expandedRows[s.email]}`}
                            key={`${s.email}-jobs`}
                          >
                            <td colSpan="100%">
                              <div className="job-subrow-content">
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
                                  {loadingJobs[s.email] ? (
                                    <tr className="no-jobs-row">
                                      <td colSpan="6">Loading...</td>
                                    </tr>
                                  ) : jobsByEmail[s.email] && jobsByEmail[s.email].length > 0 ? (
                                    jobsByEmail[s.email].map((job, index) => (
                                      <tr
                                        key={index}
                                        onMouseEnter={(e) => handleJobEnter(job, e)}
                                        onMouseLeave={handleJobLeave}
                                        onClick={(e) => handleJobClick(job, e)}
                                      >
                                        <td>{job.job_title}</td>
                                        <td>
                                          {job.min_pay && job.max_pay
                                            ? `${job.min_pay} - ${job.max_pay}`
                                            : 'N/A'}
                                        </td>
                                        <td>{job.source || 'N/A'}</td>
                                        <td>
                                          {loadingJobDescriptions[job.job_code] ? (
                                            <span>Generating...</span>
                                          ) : (
                                            <div className="job-action-group">
                                              <button
                                                onClick={() =>
                                                  jobDescriptionStatus[job.job_code] === 'ready'
                                                    ? viewJobDescription(
                                                        job.job_code,
                                                        s.email
                                                      )
                                                    : handleGenerateJobDescription(
                                                        job.job_code,
                                                        s.email
                                                      )
                                                }
                                                className="job-action-btn"
                                              >
                                                View JD
                                              </button>
                                              <button
                                                onClick={() =>
                                                  resendJobDescription(
                                                    job.job_code,
                                                    s.email
                                                  )
                                                }
                                                className="job-action-btn"
                                              >
                                                Resend
                                              </button>
                                            </div>
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
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
                </table>
              </div>
              {nextCursor && (
                <div style={{ textAlign: 'center', margin: '1rem 0' }}>
                  <button onClick={() => fetchStudents(nextCursor)}>Load More</button>
                </div>
              )}
              </>
            ) : (
              <p>You haven't created any student profiles.</p>
            )}
          </div>
        </div>
        )}
      </div>
      {drawerOpen && (
        <>
          <div className="drawer-overlay" onClick={closeDrawer}></div>
          <div className="drawer-panel">
            <Suspense fallback={<div>Loading...</div>}>
              <StudentForm
                title="Edit Student Profile"
                initialData={editingStudent}
                licenses={licenses}
                onSubmit={handleUpdate}
                onCancel={closeDrawer}
                isSaving={isSaving}
              />
            </Suspense>
          </div>
        </>
      )}
      {modalNotes && (
        <Suspense fallback={null}>
          <NotesHistoryModal
            notes={modalNotes.notes}
            jobCode={modalNotes.jobCode}
            studentEmail={modalNotes.studentEmail}
            canAdd={modalNotes.canAdd}
            isAdmin={isAdmin}
            onClose={() => setModalNotes(null)}
          />
        </Suspense>
      )}
      {hoveredJob && (
        <div
          className="tracking-popover"
          style={{ top: hoveredJob.position.top, left: hoveredJob.position.left }}
        >
          <table>
            <tbody>
              <tr>
                <td>Email sent:</td>
                <td>{formatDate(hoveredJob.job.email_sent)}</td>
              </tr>
              <tr>
                <td>Email opened:</td>
                <td>{formatDate(hoveredJob.job.first_open)}</td>
              </tr>
              <tr>
                <td>Application link clicked:</td>
                <td>{hoveredJob.job.clicked ? 'Yes' : 'No'}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      </div>
    </div>
  );
}

export default StudentProfiles;
