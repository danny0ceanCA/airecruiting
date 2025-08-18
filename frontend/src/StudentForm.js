import React, { useState, useEffect, useRef } from 'react';
import loadGoogleMaps from './utils/loadGoogleMaps';
import './StudentForm.css';

const initialState = {
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
};

function StudentForm({ title, initialData = {}, licenses = [], onSubmit, onCancel, isSaving }) {
  const [formData, setFormData] = useState({ ...initialState, ...initialData });
  const [formError, setFormError] = useState('');
  const cityRef = useRef(null);

  useEffect(() => {
    setFormData({ ...initialState, ...initialData });
  }, [initialData]);

  useEffect(() => {
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
    loadGoogleMaps(initAutocomplete);
  }, []);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const validate = () => {
    if (!formData.first_name || !formData.last_name || !formData.email) {
      setFormError('First name, last name and email are required.');
      return false;
    }
    setFormError('');
    return true;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validate()) return;
    const studentData = {
      ...formData,
      skills: formData.skills.split(',').map((s) => s.trim()),
      interests: formData.interests.trim(),
      lat: parseFloat(formData.lat || 0),
      lng: parseFloat(formData.lng || 0),
      max_travel: parseFloat(formData.max_travel || 0)
    };
    const result = await onSubmit(studentData);
    if (result !== false) {
      setFormData(initialState);
    }
  };

  return (
    <form className="student-form" onSubmit={handleSubmit}>
      <h2>{title}</h2>
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
      <textarea id="experience_summary" name="experience_summary" rows={4} value={formData.experience_summary} onChange={handleChange} />
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
      <div className="form-actions">
        <button type="submit" disabled={isSaving}>
          {isSaving ? <><span className="spinner" /> Saving...</> : 'Save'}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="cancel-btn">Cancel</button>
        )}
      </div>
      {formError && <p className="error">{formError}</p>}
    </form>
  );
}

export default StudentForm;

