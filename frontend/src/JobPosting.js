import React, { useCallback, useEffect, useState, useRef } from 'react';
import { Navigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import api from './api';
import AdminMenu from './AdminMenu';
import loadGoogleMaps from './utils/loadGoogleMaps';
import './JobPosting.css';
import NotesHistoryModal from './NotesHistoryModal';

function JobPosting() {
  const [formData, setFormData] = useState({
    job_title: '',
    job_description: '',
    desired_skills: '',
    required_license: '',
    source: '',
    external_apply_url: '',
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
  const [createdFilter, setCreatedFilter] = useState('');
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
  const [previewingResumes, setPreviewingResumes] = useState({});
  const [activeTab, setActiveTab] = useState('jobs');
  const [licenses, setLicenses] = useState([]);
  const [schoolCodes, setSchoolCodes] = useState([]);
  const [blastForm, setBlastForm] = useState({
    subject: '',
    body: '',
    institutionalCodes: [],
    license: '',
    source: ''
  });
  const [blastSubmitting, setBlastSubmitting] = useState(false);
  const [blastFeedback, setBlastFeedback] = useState(null);
  const [blastError, setBlastError] = useState(null);
  const [blastStats, setBlastStats] = useState(null);
  const [blastHistory, setBlastHistory] = useState([]);
  const [blastHistoryLoading, setBlastHistoryLoading] = useState(false);
  const [blastHistoryError, setBlastHistoryError] = useState(null);
  const [expandedBlast, setExpandedBlast] = useState(null);
  const [blastDetails, setBlastDetails] = useState({});
  const [blastDetailsLoading, setBlastDetailsLoading] = useState({});
  const [blastDetailsError, setBlastDetailsError] = useState({});
  const pollingIntervalsRef = useRef({});
  const pollingMetadataRef = useRef({});
  const isMountedRef = useRef(true);

  const licenseLabel = (code) => {
    const l = licenses.find((x) => x.code === code);
    return l ? l.label : code;
  };
  const [modalNotes, setModalNotes] = useState(null);

  const formatDateTime = (value) => {
    if (!value) {
      return '—';
    }
    try {
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) {
        return value;
      }
      return parsed.toLocaleString();
    } catch (err) {
      return value;
    }
  };

  const calculateOpenRate = (stats = {}, fallbackSent = 0) => {
    const sentCount = stats.sent ?? fallbackSent ?? 0;
    const uniqueOpens = stats.unique_opens ?? 0;
    if (!sentCount) {
      return '0%';
    }
    const percent = Math.round((uniqueOpens / sentCount) * 1000) / 10;
    return `${Number.isInteger(percent) ? percent.toFixed(0) : percent.toFixed(1)}%`;
  };

  const blastStatusLabel = (status) => {
    if (!status) {
      return 'Pending';
    }
    switch (status) {
      case 'sent':
        return 'Sent';
      case 'failed':
        return 'Failed';
      case 'opened':
        return 'Opened';
      case 'pending':
        return 'Pending';
      default:
        return status.charAt(0).toUpperCase() + status.slice(1);
    }
  };

  const locationRef = useRef(null);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const initLocationAutocomplete = () => {
    if (locationRef.current && window.google) {
      const ac = new window.google.maps.places.Autocomplete(locationRef.current, { types: ['(cities)'] });
      ac.addListener('place_changed', () => {
        const place = ac.getPlace();
        if (!place.geometry || !place.geometry.location) {
          console.warn('No geometry for selected place', place);
          return;
        }
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

  useEffect(() => {
    const loadLookups = async () => {
      try {
        const resp = await api.get('/licenses');
        setLicenses(resp.data.licenses || []);
      } catch (err) {
        console.error('Failed to fetch licenses', err);
      }

      try {
        const resp = await api.get('/school-codes');
        setSchoolCodes(resp.data.codes || []);
      } catch (err) {
        console.error('Failed to fetch school codes', err);
      }
    };
    loadLookups();
  }, []);

  const handleBlastFormChange = (event) => {
    const { name, value, options } = event.target;
    if (name === 'institutionalCodes') {
      const selected = Array.from(options || [])
        .filter((option) => option.selected)
        .map((option) => option.value);
      setBlastForm((prev) => ({ ...prev, institutionalCodes: selected }));
      return;
    }

    setBlastForm((prev) => ({ ...prev, [name]: value }));
  };

  const loadBlastHistory = useCallback(async () => {
    setBlastHistoryError(null);
    setBlastHistoryLoading(true);
    try {
      const resp = await api.get('/email-blasts');
      const history = resp?.data?.blasts || [];
      if (isMountedRef.current) {
        setBlastHistory(history);
      }
    } catch (err) {
      console.error('Failed to load email blasts', err);
      if (isMountedRef.current) {
        setBlastHistoryError('Failed to load email blasts.');
      }
    } finally {
      if (isMountedRef.current) {
        setBlastHistoryLoading(false);
      }
    }
  }, []);

  const loadBlastDetails = useCallback(
    async (blastId) => {
      if (!blastId) {
        return;
      }
      setBlastDetailsError((prev) => ({ ...prev, [blastId]: null }));
      setBlastDetailsLoading((prev) => ({ ...prev, [blastId]: true }));
      try {
        const resp = await api.get(`/email-blasts/${blastId}`);
        if (isMountedRef.current) {
          setBlastDetails((prev) => ({ ...prev, [blastId]: resp?.data || {} }));
        }
      } catch (err) {
        console.error('Failed to load blast details', err);
        if (isMountedRef.current) {
          setBlastDetailsError((prev) => ({
            ...prev,
            [blastId]: 'Failed to load blast details.'
          }));
        }
      } finally {
        if (isMountedRef.current) {
          setBlastDetailsLoading((prev) => ({ ...prev, [blastId]: false }));
        }
      }
    },
    []
  );

  const handleBlastToggle = useCallback(
    (blastId) => {
      setExpandedBlast((prev) => {
        const next = prev === blastId ? null : blastId;
        if (prev !== blastId && !blastDetails[blastId] && !blastDetailsLoading[blastId]) {
          loadBlastDetails(blastId);
        }
        return next;
      });
    },
    [blastDetails, blastDetailsLoading, loadBlastDetails]
  );

  useEffect(() => {
    if (activeTab === 'blast') {
      loadBlastHistory();
    }
  }, [activeTab, loadBlastHistory]);

  const handleBlastSubmit = async (event) => {
    event.preventDefault();
    setBlastError(null);
    setBlastFeedback(null);
    setBlastStats(null);

    const subject = blastForm.subject.trim();
    const body = blastForm.body.trim();
    const source = blastForm.source.trim();

    if (!subject || !body) {
      setBlastError('Subject and message are required.');
      return;
    }

    const hasFilters =
      (blastForm.institutionalCodes && blastForm.institutionalCodes.length > 0) ||
      (blastForm.license && blastForm.license.trim()) ||
      source;

    if (!hasFilters) {
      setBlastError('Select at least one recipient filter.');
      return;
    }

    const payload = {
      subject,
      body,
      institutional_codes: blastForm.institutionalCodes
    };

    if (blastForm.license) {
      payload.license = blastForm.license;
    }

    if (source) {
      payload.source = source;
    }

    setBlastSubmitting(true);

    try {
      const resp = await api.post('/email-blast', payload);
      const data = resp.data || {};
      setBlastStats(data);
      const sent = data.sent ?? 0;
      const matched = data.matched ?? sent;
      const failed = data.failed ?? 0;
      const suffix = matched === 1 ? '' : 's';
      const failureSuffix = failed ? ` (${failed} failed)` : '';
      setBlastFeedback(`Blast sent to ${sent} of ${matched} matched student${suffix}${failureSuffix}.`);
      setBlastForm({
        subject: '',
        body: '',
        institutionalCodes: [],
        license: '',
        source: ''
      });
      await loadBlastHistory();
      if (data.blast_id) {
        setExpandedBlast(data.blast_id);
        loadBlastDetails(data.blast_id);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setBlastError(detail || 'Failed to send email blast.');
    } finally {
      setBlastSubmitting(false);
    }
  };

  const token = localStorage.getItem('token');
  const decoded = token ? jwtDecode(token) : {};
  const userRole = decoded?.role;
  const { sub: email } = decoded;
  const isAdmin = userRole === 'admin' || userRole === 'junior_admin';
  const isRecruiter = userRole === 'recruiter';
  const isCareer = userRole === 'career' || userRole === 'career_director';
  const canMatchJobs = isAdmin || isRecruiter || isCareer;
  const canUseBlast = isAdmin || isRecruiter;
  const canAccessJobsPage = isAdmin || isRecruiter || isCareer;
  const shouldRedirect = !canAccessJobsPage;


  const formatJobDate = (value) => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit'
    });
  };

  const formatJobLocation = (job) => {
    const city = job?.city?.trim();
    const state = job?.state?.trim();
    if (city && state) return `${city}, ${state}`;
    if (city) return city;
    if (state) return state;
    return '';
  };

  const fetchJobs = async () => {
    try {
      const resp = await api.get('/jobs', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const allJobs = resp.data.jobs || [];
      const visibleJobs = isAdmin
        ? allJobs
        : allJobs.filter((job) => job.posted_by === email);
      const sorted = [...visibleJobs].sort((a, b) => {
        const aTime = a?.timestamp ? new Date(a.timestamp).getTime() : 0;
        const bTime = b?.timestamp ? new Date(b.timestamp).getTime() : 0;
        const safeATime = Number.isNaN(aTime) ? 0 : aTime;
        const safeBTime = Number.isNaN(bTime) ? 0 : bTime;
        return safeBTime - safeATime;
      });
      setJobs(sorted);
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
        const status = resp.data.status;
        const hasResults = Array.isArray(resp.data.results) && resp.data.results.length > 0;
        result[job.job_code] = status === 'complete' && hasResults;
      } catch {
        result[job.job_code] = false;
      }
    }
    setMatchPresence(result);
  };

  const loadMatchResults = useCallback(
    async (job, existingResp = null) => {
      let jobCode = typeof job === 'string' ? job : job?.job_code;

      if (typeof job === 'string') {
        const foundJob = jobs.find(
          (j) =>
            j.job_code === job ||
            String(j.id) === String(job) ||
            String(j.job_id) === String(job)
        );
        jobCode = foundJob?.job_code || jobCode;
      }

      if (!jobCode) {
        console.warn('No job code provided for loadMatchResults', job);
        return;
      }

      try {
        const resp =
          existingResp ||
          (await api.get(`/match/${jobCode}`, {
            headers: { Authorization: `Bearer ${token}` }
          }));
        const raw = resp.data.results || [];
        console.log('🔎 Loaded match results API response:', resp.data);
        const matchResults = raw.map((m) => ({
          ...m,
          status: m.status || null
        }));
        setMatches((prev) => ({ ...prev, [jobCode]: matchResults }));
        setMatchLoaded((prev) => ({ ...prev, [jobCode]: true }));
        setMatchPresence((prev) => ({
          ...prev,
          [jobCode]: matchResults.length > 0 || prev[jobCode],
        }));
      } catch (err) {
        console.error(`Error loading stored matches for ${jobCode}:`, err);
        setMatchLoaded((prev) => ({ ...prev, [jobCode]: true }));
      }
    },
    [jobs, token]
  );

  const stopPollingJob = useCallback((jobKey) => {
    if (!jobKey) {
      return;
    }

    const intervalId = pollingIntervalsRef.current[jobKey];
    if (intervalId) {
      clearInterval(intervalId);
      delete pollingIntervalsRef.current[jobKey];
      console.debug(`[frontend-debug] Stopped polling for job ${jobKey}`);
    }

    if (pollingMetadataRef.current[jobKey]) {
      delete pollingMetadataRef.current[jobKey];
    }
  }, []);

  const startPollingJob = useCallback(
    (jobId, jobCode) => {
      const jobKey = String(jobId || jobCode || '');

      if (!jobKey) {
        console.warn('Cannot start polling without job identifier', jobId, jobCode);
        return;
      }

      const resolvedJobCode = jobCode || jobKey;

      stopPollingJob(jobKey);

      pollingMetadataRef.current[jobKey] = { jobCode: resolvedJobCode };

      console.debug(`[frontend-debug] Started polling /has-match for job ${jobKey}`);

      const poll = async () => {
        try {
          const resp = await api.get(`/has-match/${jobKey}`, {
            headers: { Authorization: `Bearer ${token}` }
          });

          if (resp.data.status === 'complete') {
            if (!isMountedRef.current) {
              stopPollingJob(jobKey);
              return;
            }

            const results = Array.isArray(resp.data.results) ? resp.data.results : [];

            if (results.length > 0) {
              console.debug(`[frontend-debug] Job ${jobKey} complete with ${results.length} results`);
              const mappedResults = results.map((m) => ({
                ...m,
                status: m.status || null,
              }));
              setMatches((prev) => ({ ...prev, [resolvedJobCode]: mappedResults }));
              setMatchLoaded((prev) => ({ ...prev, [resolvedJobCode]: true }));
              setMatchPresence((prev) => ({ ...prev, [resolvedJobCode]: true }));
            } else {
              await loadMatchResults(resolvedJobCode);
            }

            setLoadingMatches((prev) => ({ ...prev, [resolvedJobCode]: false }));
            stopPollingJob(jobKey);
          }
        } catch (err) {
          console.error(`Error polling match status for ${jobKey}:`, err);
        }
      };

      poll();
      const intervalId = setInterval(poll, 2000);
      pollingIntervalsRef.current[jobKey] = intervalId;
    },
    [loadMatchResults, stopPollingJob, token]
  );

  useEffect(() => {
    if (!canUseBlast && activeTab === 'blast') {
      setActiveTab('jobs');
    }
  }, [activeTab, canUseBlast]);

  useEffect(() => {
    return () => {
      Object.keys(pollingIntervalsRef.current).forEach((jobKey) => {
        stopPollingJob(jobKey);
      });
    };
  }, [stopPollingJob]);

  useEffect(() => {
    Object.entries(pollingMetadataRef.current).forEach(([jobKey, metadata]) => {
      const jobCode = metadata?.jobCode || jobKey;
      const isLoading = Boolean(loadingMatches[jobCode]);
      const hasLoaded = Boolean(matchLoaded[jobCode]);
      const hasResults = Array.isArray(matches[jobCode]) && matches[jobCode].length > 0;

      if (!isLoading && (hasLoaded || hasResults)) {
        stopPollingJob(jobKey);
      }
    });
  }, [matches, matchLoaded, loadingMatches, stopPollingJob]);

  useEffect(() => {
    const activeIdentifiers = new Set(
      jobs.map((job) => String(job.job_id ?? job.id ?? job.job_code ?? ''))
    );
    const activeCodes = new Set(jobs.map((job) => job.job_code));

    Object.keys(pollingMetadataRef.current).forEach((jobKey) => {
      const jobCode = pollingMetadataRef.current[jobKey]?.jobCode;
      const stillExists = activeIdentifiers.has(jobKey) || (jobCode && activeCodes.has(jobCode));

      if (!stillExists) {
        stopPollingJob(jobKey);
      }
    });
  }, [jobs, stopPollingJob]);

  useEffect(() => {
    jobs.forEach((job) => {
      const assignedCount = job.assigned_students?.length || 0;
      if (
        assignedCount > 0 &&
        !matches[job.job_code] &&
        !matchLoaded[job.job_code]
      ) {
        console.debug(
          `🧭 [debug] Preloading matches for assigned students on job ${job.job_code} (assigned count: ${assignedCount})`
        );
        loadMatchResults(job.job_code);
      }
    });
  }, [jobs, matches, matchLoaded, loadMatchResults]);

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
    if (!expandedJob) {
      return;
    }

    const alreadyLoaded = matchLoaded[expandedJob];
    const currentlyLoading = loadingMatches[expandedJob];

    if (!alreadyLoaded && !currentlyLoading) {
      loadMatchResults(expandedJob);
    }
  }, [expandedJob, matchLoaded, loadingMatches, loadMatchResults]);

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
        required_license: formData.required_license,
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
      if (formData.external_apply_url) {
        payload.external_apply_url = formData.external_apply_url;
        if (!payload.source) {
          setMessage('Source is required when providing an external apply URL');
          return;
        }
      }
      const resp = await api.post('/jobs', payload, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMessage(`Job posted successfully! Job code: ${resp.data.job_code}`);
      setFormData({
        job_title: '', job_description: '', desired_skills: '', required_license: '', source: '', external_apply_url: '', min_pay: '', max_pay: '', city: '', state: '', lat: '', lng: ''
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
      if (Array.isArray(resp.data.results)) {
        const matchResults = resp.data.results.map((m) => ({ ...m, status: m.status || null }));
        setMatches((prev) => ({ ...prev, [code]: matchResults }));
        setLoadingMatches((prev) => ({ ...prev, [code]: false }));
        setMatchPresence((prev) => ({ ...prev, [code]: true }));
        setMatchLoaded((prev) => ({ ...prev, [code]: true }));
      } else {
        const jobId = resp.data.job_id || code;
        startPollingJob(jobId, code);
      }
    } catch (err) {
      console.error('Error matching job:', err);
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
      if (Array.isArray(resp.data.results)) {
        const matchResults = resp.data.results.map((m) => ({ ...m, status: m.status || null }));
        setMatches((prev) => ({ ...prev, [code]: matchResults }));
        setLoadingMatches((prev) => ({ ...prev, [code]: false }));
        setMatchPresence((prev) => ({ ...prev, [code]: true }));
        setMatchLoaded((prev) => ({ ...prev, [code]: true }));
      } else {
        const jobId = resp.data.job_id || code;
        startPollingJob(jobId, code);
      }
    } catch (err) {
      console.error('Error rematching job:', err);
      setLoadingMatches((prev) => ({ ...prev, [code]: false }));
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
      return true;
    } catch (err) {
      console.error('Assign failed', err.response?.data || err.message);
      alert('Failed to assign candidate to job');
      return false;
    }
  };

  const handleNotifyCandidate = async (job, row) => {
    const assigned = await handleAssign(job, row);
    if (!assigned) {
      alert('Assignment failed; notification not sent');
      return;
    }
    await notifyInterest(job.job_code, row.email);
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
      console.error('Notification failed', err.response?.data || err.message);
      const detail = err.response?.data?.detail || 'Failed to notify candidate';
      alert(detail);
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

  const openNotes = (job, row) => {
    setModalNotes({
      notes: row.notes || [],
      jobCode: job.job_code,
      studentEmail: row.email,
      canAdd:
        (isAdmin || isRecruiter || isCareer) &&
        job.posted_by === email &&
        row.status === 'assigned',
      onSaved: (newNote) => {
        setMatches((prev) => ({
          ...prev,
          [job.job_code]: (prev[job.job_code] || []).map((m) =>
            m.email === row.email
              ? { ...m, note: newNote.text, notes: [...(m.notes || []), newNote] }
              : m
          ),
        }));
      },
    });
  };


  const rejectAssigned = async (jobCode, email) => {
    try {
      await api.post(
        '/reject-assigned',
        { job_code: jobCode, student_email: email },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMatches((prev) => ({
        ...prev,
        [jobCode]: prev[jobCode].map((m) =>
          m.email === email ? { ...m, status: 'rejected' } : m
        )
      }));
      setJobs((prevJobs) =>
        prevJobs.map((j) =>
          j.job_code === jobCode
            ? {
                ...j,
                assigned_students: (j.assigned_students || []).filter(
                  (em) => em !== email
                ),
              }
            : j
        )
      );
    } catch (err) {
      console.error('Reject failed', err);
    }
  };

  const bulkAssign = async (job) => {
    const emails = selectedRows[job.job_code] || [];
    for (const email of emails) {
      try {
        await api.post(
          '/assign',
          {
            student_email: email,
            job_code: job.job_code,
          },
          { headers: { Authorization: `Bearer ${token}` } }
        );
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
    const key = `${jobCode}:${email}`;
    setPreviewingResumes((prev) => ({ ...prev, [key]: true }));
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
      console.error('View resume error:', err);
    } finally {
      setPreviewingResumes((prev) => ({ ...prev, [key]: false }));
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
  const formatScore = (score) =>
    score !== null && score !== undefined ? Number(score).toFixed(2) : 'N/A';

  const renderMatches = (job) => {
    const matchList = matches[job.job_code] || [];
    const unassignedMatches = matchList.filter(
      (m) => m.status !== 'assigned' && m.status !== 'placed'
    );
    return (
      <>
        {loadingMatches[job.job_code] && (
          <div className="loader-bar">
            <span className="spinner" /> Loading matches...
          </div>
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
              <th>Resume</th>
              <th>Note</th>
              <th>Status</th>
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
            ) : unassignedMatches.length === 0 ? (
              <tr>
                <td colSpan="100%" className="match-prompt">
                  No new matches available. Check the Assigned tab to review previously
                  matched students.
                </td>
              </tr>
            ) : (
              unassignedMatches.map((row) => {
                const selectedCount = selectedRows[job.job_code]?.length || 0;
                const checked = selectedRows[job.job_code]?.includes(row.email);
                const disableCheckbox =
                  row.status !== null || (selectedCount >= 3 && !checked);
                return (
                  <tr key={row.email}>
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
                    <td>{formatScore(row.score)}</td>
                    <td>
                      {previewingResumes[`${job.job_code}:${row.email}`] ? (
                        <span className="spinner" />
                      ) : (
                        <button
                          className="preview-button"
                          onClick={() => previewResume(row.email, job.job_code)}
                        >
                          View Resume
                        </button>
                      )}
                    </td>
                    <td>
                      <button onClick={() => openNotes(job, row)}>
                        View Notes{row.notes && ` (${row.notes.length})`}
                      </button>
                    </td>
                    <td className="status-cell">
                      {row.status === 'placed' ? (
                        <span className="badge placed inline">Placed</span>
                      ) : row.status === 'assigned' ? (
                        <span className="badge assigned inline">Assigned</span>
                      ) : row.status === 'rejected' ? (
                        <span className="badge rejected inline">Rejected</span>
                      ) : null}
                    </td>
                    <td>
                      {row.status === null && (
                        <>
                          <button onClick={() => handleNotifyCandidate(job, row)}>Notify Candidate</button>
                          <button onClick={() => markNotInterested(job.job_code, row.email)}>Not Interested</button>
                          {!isRecruiter && (
                            <button onClick={() => handlePlace(job, row)}>Place</button>
                          )}
                        </>
                      )}
                      {row.status === 'assigned' && !isRecruiter && (
                        <button onClick={() => handlePlace(job, row)}>Place</button>
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
    const jobAssigned = job.assigned_students || [];
    const assignedMap = new Map();

    matchList.forEach((m) => {
      if (m.status === 'assigned' || jobAssigned.includes(m.email)) {
        assignedMap.set(m.email, m);
      }
    });

    jobAssigned.forEach((email) => {
      if (!assignedMap.has(email)) {
        assignedMap.set(email, {
          email,
          first_name: '',
          last_name: '',
          name: '',
          score: null,
          status: 'assigned',
          notes: [],
        });
      }
    });

    const assignedRows = Array.from(assignedMap.values());

    console.debug(
      `🧾 [debug] Rendering assigned table for job ${job.job_code} with ${assignedRows.length} rows (assigned_students length: ${jobAssigned.length})`
    );

    if (assignedRows.length === 0) {
      return (
        <div className="assigned-subtable">
          <h4>Assigned Students</h4>
          <p>No assigned students yet.</p>
        </div>
      );
    }

    return (
      <div className="assigned-subtable">
        <h4>Assigned Students</h4>
        <table className="matches-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Score</th>
              <th>Resume</th>
              <th>Note</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {assignedRows.map((row) => {
              const displayName = `${
                row.first_name || row.name?.split(' ')[0] || ''
              } ${row.last_name || row.name?.split(' ')[1] || ''}`.trim();
              const status = row.status || 'assigned';
              return (
                <tr key={row.email}>
                  <td>{displayName || row.email}</td>
                  <td>{formatScore(row.score)}</td>
                  <td>
                    {previewingResumes[`${job.job_code}:${row.email}`] ? (
                      <span className="spinner" />
                    ) : (
                      <button
                        className="preview-button"
                        onClick={() => previewResume(row.email, job.job_code)}
                      >
                        View Resume
                      </button>
                    )}
                  </td>
                  <td>
                    <button onClick={() => openNotes(job, row)}>
                      View Notes{row.notes && ` (${row.notes.length})`}
                    </button>
                  </td>
                  <td className="status-cell">
                    {status === 'placed' ? (
                      <span className="badge placed inline">Placed</span>
                    ) : status === 'rejected' ? (
                      <span className="badge rejected inline">Rejected</span>
                    ) : (
                      <span className="badge assigned inline">Assigned</span>
                    )}
                  </td>
                  <td>
                    {isRecruiter ? (
                      <>
                        <button onClick={() => notifyInterest(job.job_code, row.email)}>
                          Notify Candidate
                        </button>
                        <button onClick={() => notifyInterest(job.job_code, row.email)}>
                          Resend Job Description
                        </button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => handlePlace(job, row)}>Place</button>
                        <button onClick={() => notifyInterest(job.job_code, row.email)}>
                          Resend Job Description
                        </button>
                      </>
                    )}
                    <button onClick={() => rejectAssigned(job.job_code, row.email)}>
                      Not Interested
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {placedMatches.map((row) => (
            <tr key={row.email}>
              <td>{row.name}</td>
              <td>{row.email}</td>
              <td>{formatScore(row.score)}</td>
              <td>
                <button onClick={() => openNotes(job, row)}>
                  View Notes{row.notes && ` (${row.notes.length})`}
                </button>
              </td>
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
    const createdMatch = formatJobDate(j.timestamp)
      .toLowerCase()
      .includes(createdFilter.toLowerCase());
    return codeMatch && titleMatch && sourceMatch && createdMatch;
  };
  const filteredJobs = jobs.filter(matchFilter);
  const jobsTabLabel = isCareer ? 'My Jobs' : 'Jobs';

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
          {jobsTabLabel}
        </button>
        <button
          className={`tab ${activeTab === 'post' ? 'active' : ''}`}
          onClick={() => setActiveTab('post')}
        >
          Post a Job
        </button>
        {canUseBlast && (
          <button
            className={`tab ${activeTab === 'blast' ? 'active' : ''}`}
            onClick={() => setActiveTab('blast')}
          >
            Email Blast
          </button>
        )}
      </div>
      <div className="tab-content">
        {activeTab === 'blast' && canUseBlast && (
          <div className="blast-content">
            <div className="blast-panel">
              <form className="blast-form" onSubmit={handleBlastSubmit}>
                <h2>Email Blast</h2>
                <div className="blast-field">
                  <label htmlFor="blast-subject">Subject</label>
                  <input
                    id="blast-subject"
                    name="subject"
                    type="text"
                    value={blastForm.subject}
                    onChange={handleBlastFormChange}
                    placeholder="Enter an email subject"
                  />
                </div>
                <div className="blast-field">
                  <label htmlFor="blast-body">Message</label>
                  <textarea
                    id="blast-body"
                    name="body"
                    rows={8}
                    value={blastForm.body}
                    onChange={handleBlastFormChange}
                    placeholder="Write the email you want to send"
                  ></textarea>
                  <small>
                    Use <code>{'{{first_name}}'}</code> to insert a student's first name. If no
                    name is available, the blast will say &quot;there&quot; instead.
                  </small>
                </div>
                <div className="blast-field">
                  <label htmlFor="blast-institutional-codes">Institutional Codes</label>
                  <select
                    id="blast-institutional-codes"
                    name="institutionalCodes"
                    multiple
                    value={blastForm.institutionalCodes}
                    onChange={handleBlastFormChange}
                  >
                    {schoolCodes.map((code) => (
                      <option key={code.code} value={code.code}>
                        {code.code} — {code.label}
                      </option>
                    ))}
                  </select>
                  <small>Select one or more codes to target a specific school.</small>
                </div>
                <div className="blast-field">
                  <label htmlFor="blast-license">License</label>
                  <select
                    id="blast-license"
                    name="license"
                    value={blastForm.license}
                    onChange={handleBlastFormChange}
                  >
                    <option value="">All Licenses</option>
                    {licenses.map((l) => (
                      <option key={l.code} value={l.code}>
                        {l.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="blast-field">
                  <label htmlFor="blast-source">Source</label>
                  <input
                    id="blast-source"
                    name="source"
                    type="text"
                    value={blastForm.source}
                    onChange={handleBlastFormChange}
                    placeholder="Filter by student source (optional)"
                  />
                </div>
                <div className="blast-actions">
                  <button type="submit" disabled={blastSubmitting}>
                    {blastSubmitting ? 'Sending…' : 'Send Email Blast'}
                  </button>
                </div>
                {blastFeedback && <div className="blast-feedback">{blastFeedback}</div>}
                {blastError && <div className="blast-error">{blastError}</div>}
                {blastStats && (
                  <div className="blast-stats">
                    <div><strong>Matched:</strong> {blastStats.matched ?? 0}</div>
                    <div><strong>Sent:</strong> {blastStats.sent ?? 0}</div>
                    <div><strong>Failed:</strong> {blastStats.failed ?? 0}</div>
                    {blastStats.skipped_missing_email ? (
                      <div>
                        <strong>Skipped (missing email):</strong> {blastStats.skipped_missing_email}
                      </div>
                    ) : null}
                    {blastStats.skipped_filtered ? (
                      <div>
                        <strong>Skipped (filters):</strong> {blastStats.skipped_filtered}
                      </div>
                    ) : null}
                  </div>
                )}
              </form>
            </div>
            <div className="blast-history">
              <div className="blast-history-header">
                <h2>Blast History</h2>
                <button
                  type="button"
                  onClick={loadBlastHistory}
                  disabled={blastHistoryLoading}
                  className="blast-history-refresh"
                >
                  {blastHistoryLoading ? 'Refreshing…' : 'Refresh'}
                </button>
              </div>
              {blastHistoryError && (
                <div className="blast-error blast-history-error">{blastHistoryError}</div>
              )}
              <div className="blast-history-table-wrapper">
                {blastHistoryLoading && blastHistory.length === 0 ? (
                  <div className="blast-history-loading">Loading email blasts…</div>
                ) : blastHistory.length === 0 ? (
                  <div className="blast-history-empty">No email blasts have been sent yet.</div>
                ) : (
                  <table className="blast-history-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>Subject</th>
                        <th>Sent</th>
                        <th>Delivered</th>
                        <th>Unique Opens</th>
                        <th>Open Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {blastHistory.map((blast) => {
                        const stats = blast.stats || {};
                        const sentCount = stats.sent ?? blast.sent ?? 0;
                        const uniqueOpens = stats.unique_opens ?? 0;
                        const isExpanded = expandedBlast === blast.blast_id;
                        return (
                          <React.Fragment key={blast.blast_id}>
                            <tr className="blast-row">
                              <td className="blast-expand-cell">
                                <button
                                  type="button"
                                  className="expand-toggle"
                                  onClick={() => handleBlastToggle(blast.blast_id)}
                                  title={isExpanded ? 'Collapse' : 'Expand'}
                                >
                                  {isExpanded ? '–' : '+'}
                                </button>
                              </td>
                              <td className="blast-subject">{blast.subject}</td>
                              <td>{formatDateTime(blast.timestamp)}</td>
                              <td className="blast-metric">{sentCount}</td>
                              <td className="blast-metric">{uniqueOpens}</td>
                              <td className="blast-metric">{calculateOpenRate(stats, blast.sent)}</td>
                            </tr>
                            {isExpanded && (
                              <tr className="blast-detail-row">
                                <td colSpan={6}>
                                  {blastDetailsLoading[blast.blast_id] ? (
                                    <div className="blast-history-loading">Loading details…</div>
                                  ) : blastDetailsError[blast.blast_id] ? (
                                    <div className="blast-error">{blastDetailsError[blast.blast_id]}</div>
                                  ) : (
                                    (() => {
                                      const detail = blastDetails[blast.blast_id] || {};
                                      const detailBlast = detail.blast || blast;
                                      const detailStats = detail.stats || stats;
                                      const recipients = detail.recipients || [];
                                      const filters = detailBlast.filters || blast.filters || {};
                                      return (
                                        <div className="blast-detail">
                                          <div className="blast-summary-grid">
                                            <div><strong>Matched:</strong> {detailBlast.matched ?? blast.matched ?? 0}</div>
                                            <div><strong>Sent:</strong> {detailStats.sent ?? detailBlast.sent ?? sentCount}</div>
                                            <div><strong>Failed:</strong> {detailBlast.failed ?? blast.failed ?? 0}</div>
                                            <div><strong>Unique Opens:</strong> {detailStats.unique_opens ?? uniqueOpens}</div>
                                            <div><strong>Total Opens:</strong> {detailStats.total_opens ?? 0}</div>
                                            <div><strong>Open Rate:</strong> {calculateOpenRate(detailStats, detailBlast.sent ?? sentCount)}</div>
                                            <div><strong>Skipped (missing email):</strong> {detailBlast.skipped_missing_email ?? 0}</div>
                                            <div><strong>Skipped (filters):</strong> {detailBlast.skipped_filtered ?? 0}</div>
                                          </div>
                                          <div className="blast-detail-filters">
                                            <div><strong>Institutional Codes:</strong> {filters.institutional_codes && filters.institutional_codes.length ? filters.institutional_codes.join(', ') : 'All'}</div>
                                            <div><strong>License:</strong> {filters.license || 'All'}</div>
                                            <div><strong>Source:</strong> {filters.source || 'All'}</div>
                                          </div>
                                          {detailBlast.body_preview && (
                                            <div className="blast-detail-body">
                                              <strong>Message Preview:</strong>
                                              <p>{detailBlast.body_preview}</p>
                                            </div>
                                          )}
                                          <div className="blast-recipient-table-wrapper">
                                            {recipients.length === 0 ? (
                                              <div className="blast-history-empty">No recipient records found.</div>
                                            ) : (
                                              <table className="blast-recipient-table">
                                                <thead>
                                                  <tr>
                                                    <th>Email</th>
                                                    <th>Status</th>
                                                    <th>Sent At</th>
                                                    <th>First Open</th>
                                                    <th>Last Open</th>
                                                    <th>Opens</th>
                                                  </tr>
                                                </thead>
                                                <tbody>
                                                  {recipients.map((recipient) => (
                                                    <tr key={recipient.email}>
                                                      <td>{recipient.email}</td>
                                                      <td className={`blast-recipient-status status-${recipient.status || 'pending'}`}>
                                                        {blastStatusLabel(recipient.status)}
                                                      </td>
                                                      <td>{formatDateTime(recipient.sent_at)}</td>
                                                      <td>{formatDateTime(recipient.first_open)}</td>
                                                      <td>{formatDateTime(recipient.last_open)}</td>
                                                      <td className="blast-metric">{recipient.opens ?? 0}</td>
                                                    </tr>
                                                  ))}
                                                </tbody>
                                              </table>
                                            )}
                                          </div>
                                        </div>
                                      );
                                    })()
                                  )}
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
              <div className="form-field">
                <label htmlFor="required_license">License</label>
                <select
                  id="required_license"
                  name="required_license"
                  value={formData.required_license}
                  onChange={handleChange}
                >
                  <option value="">Select...</option>
                  {licenses.map((l) => (
                    <option key={l.code} value={l.code}>{l.label}</option>
                  ))}
                </select>
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
              {!isRecruiter && (
                <div className="form-field">
                  <label htmlFor="external_apply_url">External Apply URL</label>
                  <input
                    id="external_apply_url"
                    name="external_apply_url"
                    type="text"
                    value={formData.external_apply_url}
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
                <th>License</th>
                <th>Source</th>
                <th>Location</th>
                <th>Pay Range</th>
                <th>Created</th>
                <th>Assigned</th>
                {!isRecruiter && <th>Placed</th>}
                <th>Action</th>
              </tr>
              <tr className="filter-row">
                <th></th>
                <th>
                  <input
                    className="column-filter"
                    type="text"
                    value={codeFilter}
                    onChange={(e) => setCodeFilter(e.target.value)}
                    placeholder="Filter"
                  />
                </th>
                <th>
                  <input
                    className="column-filter"
                    type="text"
                    value={titleFilter}
                    onChange={(e) => setTitleFilter(e.target.value)}
                    placeholder="Filter"
                  />
                </th>
                <th></th>
                <th>
                  <input
                    className="column-filter"
                    type="text"
                    value={sourceFilter}
                    onChange={(e) => setSourceFilter(e.target.value)}
                    placeholder="Filter"
                  />
                </th>
                <th></th>
                <th></th>
                <th>
                  <input
                    className="column-filter"
                    type="text"
                    value={createdFilter}
                    onChange={(e) => setCreatedFilter(e.target.value)}
                    placeholder="Filter"
                  />
                </th>
                <th></th>
                {!isRecruiter && <th></th>}
                <th></th>
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
                  <td>{licenseLabel(job.required_license)}</td>
                  <td>{job.source}</td>
                  <td>{formatJobLocation(job)}</td>
                  <td>
                    {job.min_pay !== undefined && job.max_pay !== undefined
                      ? `${job.min_pay} - ${job.max_pay}`
                      : ''}
                  </td>
                  <td>{formatJobDate(job.timestamp)}</td>
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
                    {canMatchJobs ? (
                      (() => {
                        const matchListLength = matches[job.job_code]?.length || 0;
                        const hasMatchInRedis = matchPresence[job.job_code] === true;
                        const assignedCount = job.assigned_students?.length || 0;
                        const hasStoredMatches =
                          hasMatchInRedis || matchListLength > 0 || assignedCount > 0;
                        console.debug(
                          `🧠 [debug] Job ${job.job_code} button render -> matchPresence: ${hasMatchInRedis}, stored length: ${matchListLength}. Showing ${hasStoredMatches ? 'View Matches + Match Again' : 'Match only'} buttons.`
                        );

                        return hasStoredMatches ? (
                          <>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                if (hasMatchInRedis && !matches[job.job_code]) {
                                  loadMatchResults(job.job_code);
                                }
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
                      })()
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const isExpanded = expandedJob === job.job_code;
                          setExpandedJob(isExpanded ? null : job.job_code);
                          setActiveSubtab((prev) => ({
                            ...prev,
                            [job.job_code]: 'details',
                          }));
                        }}
                      >
                        View Details
                      </button>
                    )}
                  </td>
                </tr>
                {expandedJob === job.job_code && (
                  activeSubtab[job.job_code] === 'details' ? (
                    <tr className="job-details-row">
                      <td colSpan={!isRecruiter ? 10 : 9}>
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
                                <label>License</label>
                                <select
                                  value={editedJobs[job.job_code]?.required_license ?? (job.required_license || '')}
                                  onChange={(e) =>
                                    setEditedJobs((prev) => ({
                                      ...prev,
                                      [job.job_code]: {
                                        ...prev[job.job_code],
                                        required_license: e.target.value,
                                      },
                                    }))
                                  }
                                >
                                  <option value="">Select...</option>
                                  {licenses.map((l) => (
                                    <option key={l.code} value={l.code}>{l.label}</option>
                                  ))}
                                </select>
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
                              {(userRole === 'admin' || userRole === 'junior_admin') && (
                                <div className="form-row">
                                  <label>External Apply URL</label>
                                  <input
                                    type="text"
                                    value={
                                      editedJobs[job.job_code]?.external_apply_url ||
                                      job.external_apply_url ||
                                      ''
                                    }
                                    onChange={(e) =>
                                      setEditedJobs((prev) => ({
                                        ...prev,
                                        [job.job_code]: {
                                          ...prev[job.job_code],
                                          external_apply_url: e.target.value,
                                        },
                                      }))
                                    }
                                  />
                                </div>
                              )}
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
                              {job.required_license && (
                                <p>License: {licenseLabel(job.required_license)}</p>
                              )}
                              <p>Source: {job.source}</p>
                              {job.external_apply_url && (
                                <p>
                                  External Apply: <a href={job.external_apply_url} target="_blank" rel="noopener noreferrer">Apply Here</a>
                                </p>
                              )}
                              <p>
                                Pay Range: {job.min_pay} - {job.max_pay}
                              </p>
                              {(userRole === 'admin' || userRole === 'junior_admin' || job.posted_by === email) && (
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
                      <td colSpan={!isRecruiter ? 10 : 9}>
                        {activeSubtab[job.job_code] === 'matches' && renderMatches(job)}
                        {activeSubtab[job.job_code] === 'assigned' && renderAssigned(job)}
                        {activeSubtab[job.job_code] === 'placed' && renderPlaced(job)}
                        {(userRole === 'admin' || userRole === 'junior_admin') && (
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
      {modalNotes && (
        <NotesHistoryModal
          notes={modalNotes.notes}
          jobCode={modalNotes.jobCode}
          studentEmail={modalNotes.studentEmail}
          canAdd={modalNotes.canAdd}
          isAdmin={userRole === 'admin' || userRole === 'junior_admin'}
          onClose={() => setModalNotes(null)}
          onSaved={modalNotes.onSaved}
        />
      )}
    </div>
  );
}

export default JobPosting;
