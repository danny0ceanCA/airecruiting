import React, { useState } from 'react';
import api from "./api";
import { Link, useNavigate } from 'react-router-dom';
import './LoginForm.css';

function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    console.log('Submitting login...');

    if (!email.trim() || !password) {
      setError('Invalid credentials');
      return;
    }

    try {
      const resp = await api.post('/login',
        { email, password }
      );

      console.log('Response data:', resp.data);

      const token = resp.data.token || resp.data.access_token;
      if (token) {
        localStorage.setItem('token', token);
        console.log('Token stored in localStorage:', token);

        // Primary navigation
        navigate('/dashboard');

        // Fallback just in case
        setTimeout(() => {
          if (window.location.pathname !== '/dashboard') {
            console.warn('Fallback to window.location.href');
            window.location.href = '/dashboard';
          }
        }, 500);
      } else {
        console.warn('No access_token received from server.');
      }
    } catch (err) {
      console.error('Login error:', err);
      if (err.response && (err.response.status === 401 || err.response.status === 422)) {
        setError('Invalid credentials');
      } else {
        setError(err.response?.data?.detail || 'Login failed');
      }
    }
  };

  return (
    <div className="login-container">
      <form className="login-form" onSubmit={handleSubmit}>
        <h2>Login</h2>

        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        <button type="submit">Login</button>

        <Link to="/register" className="register-link">Register</Link>

        {error && <p className="error">{error}</p>}
      </form>
    </div>
  );
}

export default LoginForm;
