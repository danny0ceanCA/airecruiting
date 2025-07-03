import React from 'react';
import { Navigate } from 'react-router-dom';
import jwtDecode from 'jwt-decode';
import AdminMenu from './AdminMenu';
import './CareerStaffInfo.css';

function CareerStaffInfo() {
  const token = localStorage.getItem('token');
  let role = '';
  if (token) {
    try {
      const dec = jwtDecode(token);
      role = dec.role;
    } catch {}
  }

  if (role !== 'admin' && role !== 'career') {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="career-info-container">
      <AdminMenu />
      <h2>Welcome Career Services Team!</h2>
      <p>
        <strong>TalentMatch AI</strong> is more than a tool — it’s a platform built to empower career services teams. From student intake to confirmed placement, we streamline every step of the employment journey so you can focus on outcomes, not overhead.
      </p>
      <p>
        <strong>Smart matching begins at profile creation.</strong> TalentMatch AI instantly surfaces job opportunities that align with each student's skills, certifications, and geographic preferences — eliminating hours of manual search.
      </p>
      <p>
        <strong>AI-generated, job-specific resumes</strong> are automatically crafted for each match, helping students shine professionally without the burden of revising their resumes for every application.
      </p>
      <p>
        <strong>Transparent placement tracking</strong> keeps your team in control. Instantly see where students are assigned, which employers are engaged, and generate rich job summaries including strengths, growth areas, and coaching strategies.
      </p>
      <p>
        <strong>Built-in placement confirmation and analytics</strong> make documentation effortless. With the Metrics Module, you can track progress, measure success, and generate the insights your institution needs — all in one place.
      </p>
      <p>
        TalentMatch AI is your strategic partner in student success — intuitive, powerful, and purpose-built for career services.
      </p>
    </div>
  );
}

export default CareerStaffInfo;
