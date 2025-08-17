import React, { useState } from 'react';
import api from "./api";
import { Link, useNavigate } from 'react-router-dom';
import './RegisterForm.css';
import Button from './components/Button';
import Input from './components/Input';

function RegisterForm() {
  const [formData, setFormData] = useState({
    email: '',
    firstName: '',
    lastName: '',
    password: '',
    role: 'applicant',
  });
  const [institutionalCode, setInstitutionalCode] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (
      !formData.email.trim() ||
      !formData.firstName.trim() ||
      !formData.lastName.trim() ||
      !formData.password ||
      ((formData.role === 'career' || formData.role === 'recruiter') &&
        !institutionalCode.trim())
    ) {
      setError('All fields are required');
      return;
    }

    setLoading(true);
    try {
      const resp = await api.post('/register', {
        email: formData.email,
        first_name: formData.firstName,
        last_name: formData.lastName,
        password: formData.password,
        institutional_code: institutionalCode || undefined,
        role: formData.role,
      });
      setMessage('Registration submitted. Awaiting admin approval.');
      setTimeout(() => navigate('/login'), 3000);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((d) => d.msg).join(', '));
      } else {
        setError(detail || 'Registration failed');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="register-container">
      <form className="register-form" onSubmit={handleSubmit}>
        <h2>Register</h2>
        <label htmlFor="email">Email</label>
        <Input
          id="email"
          name="email"
          type="email"
          value={formData.email}
          onChange={handleChange}
          disabled={loading}
          error={error}
        />
        <label htmlFor="firstName">First Name</label>
        <Input
          id="firstName"
          name="firstName"
          type="text"
          value={formData.firstName}
          onChange={handleChange}
          disabled={loading}
          error={error}
        />
        <label htmlFor="lastName">Last Name</label>
        <Input
          id="lastName"
          name="lastName"
          type="text"
          value={formData.lastName}
          onChange={handleChange}
          disabled={loading}
          error={error}
        />
        <label htmlFor="role">Role</label>
        <select id="role" name="role" value={formData.role} onChange={handleChange} disabled={loading}>
          <option value="applicant">Applicant</option>
          <option value="career">Career Services</option>
          <option value="recruiter">Recruiter</option>
        </select>
        <label htmlFor="institutional_code">Institutional Code</label>
        <Input
          id="institutional_code"
          name="institutional_code"
          type="text"
          maxLength={4}
          value={institutionalCode}
          onChange={(e) => setInstitutionalCode(e.target.value)}
          disabled={loading}
          error={error}
        />
        <Link to="/request-code" className="request-code-link">Request an institutional code</Link>
        {error && <p className="error">{error}</p>}
        <label htmlFor="password">Password</label>
        <Input
          id="password"
          name="password"
          type="password"
          value={formData.password}
          onChange={handleChange}
          disabled={loading}
          error={error}
        />
        <Button type="submit" loading={loading}>Register</Button>
        <Link to="/login" className="login-link">Back to Login</Link>
        {message && <p className="message">{message}</p>}
      </form>
    </div>
  );
}

export default RegisterForm;
