import React, { useState, useEffect, useRef } from 'react';
import api from './api';
import jwtDecode from 'jwt-decode';
import AdminMenu from './AdminMenu';
import loadGoogleMaps from './utils/loadGoogleMaps';
import './StudentProfiles.css';

function ApplicantProfile() {
  const token = localStorage.getItem('token');
  const decoded = token ? jwtDecode(token) : {};
  const email = decoded.sub;

  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: email || '',
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
  const [assignedJobs, setAssignedJobs] = useState([]);
  const [isEditing, setIsEditing] = useState(false);
  const [jobDescriptionStatus, setJobDescriptionStatus] = useState({});
  const [loadingJobDescriptions, setLoadingJobDescriptions] = useState({});

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

  useEffect(() => {
    if (token) {
      fetchProfile();
    }
  }, [token]);

  const fetchProfile = async () => {
    try {
      const resp = await api.get('/students/me', { headers: { Authorization: `Bearer ${token}` } });
      const data = resp.data;
      setFormData({
        first_name: data.first_name || '',
        last_name: data.last_name || '',
        email: data.email || email,
        phone: data.phone || '',
        education_level: data.education_level || '',
        skills: Array.isArray(data.skills) ? data.skills.join(', ') : data.skills || '',
        experience_summary: data.experience_summary || '',
        interests: Array.isArray(data.interests) ? data.interests.join(', ') : data.interests || '',
        city: data.city || '',
        state: data.state || '',
        lat: data.lat || '',
        lng: data.lng || '',
        max_travel: data.max_travel || ''
      });
      setAssignedJobs(data.assigned_jobs || []);
      setIsEditing(true);
    } catch (err) {
      // no profile yet
      setIsEditing(false);
    }
  };

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      ...formData,
      skills: formData.skills.split(',').map(s => s.trim()),
      max_travel: parseFloat(formData.max_travel || 0)
    };
    try {
      if (isEditing) {
        await api.put(`/students/${email}`, payload, { headers: { Authorization: `Bearer ${token}` } });
      } else {
        await api.post('/students', payload, { headers: { Authorization: `Bearer ${token}` } });
        setIsEditing(true);
      }
      fetchProfile();
    } catch (err) {
      console.error('Save failed', err);
    }
  };

  const fetchJobDescriptionStatus = async (jobCode) => {
    try {
      const resp = await api.get(`/job-description/${jobCode}/${email}`, { headers: { Authorization: `Bearer ${token}` } });
      if (resp.data.status === 'success') {
        setJobDescriptionStatus(prev => ({ ...prev, [jobCode]: 'ready' }));
      }
    } catch {
      // ignore
    }
  };

  const generateJobDescription = async (jobCode) => {
    setLoadingJobDescriptions(prev => ({ ...prev, [jobCode]: true }));
    try {
      await api.post('/generate-job-description', { job_code: jobCode, student_email: email }, { headers: { Authorization: `Bearer ${token}` } });
      setJobDescriptionStatus(prev => ({ ...prev, [jobCode]: 'ready' }));
    } catch (err) {
      console.error('Generation failed', err);
    } finally {
      setLoadingJobDescriptions(prev => ({ ...prev, [jobCode]: false }));
    }
  };

  const viewJobDescription = async (jobCode) => {
    try {
      const resp = await api.get(`/job-description-html/${jobCode}/${email}`, { headers: { Authorization: `Bearer ${token}` } });
      const newWindow = window.open('', '_blank');
      if (newWindow) {
        newWindow.document.write(resp.data);
        newWindow.document.close();
      }
    } catch (err) {
      alert('Failed to load job description');
    }
  };

  useEffect(() => {
    assignedJobs.forEach(j => fetchJobDescriptionStatus(j.job_code));
  }, [assignedJobs]);

  return (
    <div className="profiles-container">
      <AdminMenu />
      <div className="form-panel">
        <h2>Applicant Profile</h2>
        <form className="profile-form" onSubmit={handleSubmit}>
          {['first_name','last_name','email','phone','education_level','skills','experience_summary','interests','city','state','max_travel'].map(field => (
            <React.Fragment key={field}>
              <label htmlFor={field}>{field.replace(/_/g, ' ').replace(/\b\w/g,l=>l.toUpperCase())}</label>
              {field === 'experience_summary' ? (
                <textarea id={field} name={field} value={formData[field]} onChange={handleChange} />
              ) : field === 'city' ? (
                <input id={field} ref={cityRef} name={field} type="text" value={formData[field]} onChange={handleChange} />
              ) : (
                <input id={field} name={field} type={field==='max_travel'?'number':'text'} value={formData[field]} onChange={handleChange} disabled={field==='email'} />
              )}
            </React.Fragment>
          ))}
          <button type="submit">{isEditing ? 'Update Profile' : 'Save Profile'}</button>
        </form>
      </div>
      {assignedJobs.length > 0 && (
        <div style={{marginTop:'2rem'}}>
          <h3>Matched Jobs</h3>
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
              {assignedJobs.map((job, idx) => (
                <tr key={idx}>
                  <td>{job.job_title}</td>
                  <td>{job.min_pay && job.max_pay ? `${job.min_pay} - ${job.max_pay}` : 'N/A'}</td>
                  <td>{job.source || 'N/A'}</td>
                  <td style={{textAlign:'center'}}>
                    {loadingJobDescriptions[job.job_code] ? (
                      <span>Generating...</span>
                    ) : jobDescriptionStatus[job.job_code] === 'ready' ? (
                      <button onClick={() => viewJobDescription(job.job_code)}>View</button>
                    ) : (
                      <button onClick={() => generateJobDescription(job.job_code)}>Generate</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default ApplicantProfile;
