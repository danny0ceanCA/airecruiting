import React, { useState } from 'react';
import api from "./api";
import { Link, useNavigate } from 'react-router-dom';
import './RegisterForm.css';

function RegisterForm() {
  const [formData, setFormData] = useState({
    email: '',
    firstName: '',
    lastName: '',
    password: '',
  });
  const [schoolCode, setSchoolCode] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const resp = await api.post('/register', {
        email: formData.email,
        first_name: formData.firstName,
        last_name: formData.lastName,
        password: formData.password,
        school_code: schoolCode,
      });
      setMessage('Registration submitted. Awaiting admin approval.');
      setTimeout(() => navigate('/login'), 3000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed');
    }
  };

  return (
    <div className="register-container">
      <form className="register-form" onSubmit={handleSubmit}>
        <h2>Register</h2>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          value={formData.email}
          onChange={handleChange}
        />
        <label htmlFor="firstName">First Name</label>
        <input
          id="firstName"
          name="firstName"
          type="text"
          value={formData.firstName}
          onChange={handleChange}
        />
        <label htmlFor="lastName">Last Name</label>
        <input
          id="lastName"
          name="lastName"
          type="text"
          value={formData.lastName}
          onChange={handleChange}
        />
        <label htmlFor="school_code">Enter Your School Code (e.g. 1001)</label>
        <input
          id="school_code"
          name="school_code"
          type="text"
          maxLength={4}
          value={schoolCode}
          onChange={(e) => setSchoolCode(e.target.value)}
        />
        {error && <p className="error">{error}</p>}
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          value={formData.password}
          onChange={handleChange}
        />
        <button type="submit">Register</button>
        <Link to="/login" className="login-link">Back to Login</Link>
        {message && <p className="message">{message}</p>}
      </form>
    </div>
  );
}

export default RegisterForm;
