import React, { useState, useEffect, useRef } from 'react';
import api from './api';
import jwtDecode from 'jwt-decode';
import AdminMenu from './AdminMenu';
import loadGoogleMaps from './utils/loadGoogleMaps';
import NursingNews from './NursingNews';
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
  const [assignedJobs, setAssignedJobs] = useState([]);
  const [isEditing, setIsEditing] = useState(false);
  const [jobDescriptionStatus, setJobDescriptionStatus] = useState({});
  const [loadingJobDescriptions, setLoadingJobDescriptions] = useState({});
  const [toast, setToast] = useState('');
  const [activeTab, setActiveTab] = useState('profile');

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
    if (activeTab === 'profile') {
      loadGoogleMaps(initAutocomplete);
    }
  }, [activeTab]);

  useEffect(() => {
    if (token) {
      fetchProfile();
    }
  }, [token]);

  useEffect(() => {
    const loadLicenses = async () => {
      try {
        const resp = await api.get('/licenses');
        setLicenses(resp.data.licenses || []);
      } catch (err) {
        console.error('Failed to fetch licenses', err);
      }
    };
    loadLicenses();
  }, []);

  const fetchProfile = async () => {
    try {
      const resp = await api.get('/students/me', { headers: { Authorization: `Bearer ${token}` } });
      const data = resp.data;
      setFormData({
        first_name: data.first_name || '',
        last_name: data.last_name || '',
        email: data.email || email,
        phone: data.phone || '',
        license: data.license || data.education_level || '',
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
    if (!formData.city || !formData.state) {
      alert('Please select a valid city and state.');
      return;
    }
    if (!formData.max_travel || parseFloat(formData.max_travel) <= 0) {
      alert('Please enter a travel distance greater than zero.');
      return;
    }

    const payload = {
      ...formData,
      skills: formData.skills.split(',').map(s => s.trim()),
      lat: parseFloat(formData.lat || 0),
      lng: parseFloat(formData.lng || 0),
      max_travel: parseFloat(formData.max_travel)
    };
    try {
      if (isEditing) {
        await api.put(`/students/${email}`, payload, { headers: { Authorization: `Bearer ${token}` } });
        setToast('Profile updated!');
      } else {
        await api.post('/students', payload, { headers: { Authorization: `Bearer ${token}` } });
        setIsEditing(true);
        setToast('Profile created!');
      }
      setTimeout(() => setToast(''), 3000);
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
      {toast && <div className="toast">{toast}</div>}
      <div className="tab-bar">
        <button
          className={`tab ${activeTab === 'profile' ? 'active' : ''}`}
          onClick={() => setActiveTab('profile')}
        >
          Profile
        </button>
        <button
          className={`tab ${activeTab === 'matches' ? 'active' : ''}`}
          onClick={() => setActiveTab('matches')}
        >
          Matches
        </button>
        <button
          className={`tab ${activeTab === 'news' ? 'active' : ''}`}
          onClick={() => setActiveTab('news')}
        >
          Nursing News
        </button>
        <button
          className={`tab ${activeTab === 'resources' ? 'active' : ''}`}
          onClick={() => setActiveTab('resources')}
        >
          Resources
        </button>
        <button
          className={`tab ${activeTab === 'products' ? 'active' : ''}`}
          onClick={() => setActiveTab('products')}
        >
          Products
        </button>
      </div>
      <div className="tab-content">
        {activeTab === 'profile' && (
          <div className="form-panel">
            <h2>Applicant Profile</h2>
            <form className="profile-form" onSubmit={handleSubmit}>
              <label htmlFor="first_name">First Name</label>
              <input id="first_name" name="first_name" type="text" value={formData.first_name} onChange={handleChange} />
              <label htmlFor="last_name">Last Name</label>
              <input id="last_name" name="last_name" type="text" value={formData.last_name} onChange={handleChange} />
              <label htmlFor="email">Email</label>
              <input id="email" name="email" type="text" value={formData.email} onChange={handleChange} disabled />
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
              <input id="city" name="city" type="text" value={formData.city} onChange={handleChange} ref={cityRef} required />
              <label htmlFor="state">State</label>
              <input id="state" name="state" type="text" value={formData.state} onChange={handleChange} readOnly required />
              <label htmlFor="max_travel">Max Travel</label>
              <input id="max_travel" name="max_travel" type="number" value={formData.max_travel} onChange={handleChange} required />
              <input type="hidden" id="lat" name="lat" value={formData.lat} readOnly />
              <input type="hidden" id="lng" name="lng" value={formData.lng} readOnly />
              <button type="submit">{isEditing ? 'Update Profile' : 'Save Profile'}</button>
            </form>
          </div>
        )}
        {activeTab === 'matches' && (
          <div className="form-panel">
            <h2>Matched Jobs</h2>
            {assignedJobs.length > 0 ? (
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
            ) : (
              <p>No matches found.</p>
            )}
          </div>
        )}
        {activeTab === 'news' && (
          <div className="form-panel news-panel">
            <h2>Nursing News</h2>
            <NursingNews />
          </div>
        )}
        {activeTab === 'resources' && (
          <div className="form-panel">
            <h2>Resources</h2>
            <p>Helpful links and guides for your nursing career.</p>
          </div>
        )}
        {activeTab === 'products' && (
          <div className="form-panel">
            <h2>Products</h2>
            <p>Recommended products curated for nurses.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default ApplicantProfile;
