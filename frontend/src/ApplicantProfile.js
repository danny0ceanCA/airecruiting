import React, { useEffect, useState } from 'react';
import AdminMenu from './AdminMenu';
import api from './api';
import './StudentProfiles.css';

function ApplicantProfile() {
  const [profile, setProfile] = useState(null);
  const [matches, setMatches] = useState([]);
  const token = localStorage.getItem('token');

  const fetchProfile = async () => {
    try {
      const resp = await api.get('/students/me', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setProfile(resp.data.student);
    } catch (err) {
      console.error('Failed to load profile', err);
    }
  };

  const fetchMatches = async () => {
    try {
      const resp = await api.get('/my-matches', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMatches(resp.data.matches || []);
    } catch (err) {
      console.error('Failed to load matches', err);
    }
  };

  useEffect(() => {
    if (token) {
      fetchProfile();
      fetchMatches();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!token) {
    return <p className="profiles-container">Login required.</p>;
  }

  return (
    <div className="profiles-container">
      <AdminMenu />
      <h2>My Profile</h2>
      {profile && (
        <div className="form-panel">
          <p><strong>Name:</strong> {profile.first_name} {profile.last_name}</p>
          <p><strong>Email:</strong> {profile.email}</p>
          <p><strong>Institution:</strong> {profile.institutional_code}</p>
        </div>
      )}
      <h3>Matched Jobs</h3>
      {matches.length > 0 ? (
        <table className="pending-table">
          <thead>
            <tr>
              <th>Job Code</th>
              <th>Job Title</th>
              <th>Score</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m, idx) => (
              <tr key={idx}>
                <td>{m.job_code}</td>
                <td>{m.job_title}</td>
                <td>{m.score?.toFixed(2)}</td>
                <td>{m.status || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>No matches found.</p>
      )}
    </div>
  );
}

export default ApplicantProfile;
