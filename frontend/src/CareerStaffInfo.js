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
        <strong>TalentMatch AI</strong> helps you track student profiles and match
        them with great job opportunities. Use the Student Profiles and Job
        Matching tools to quickly see recommended positions for each student.
      </p>
      <p>
        <strong>AI-driven matching</strong> surfaces personalized recommendations
        so every student is presented with openings that fit their unique
        skills.
      </p>
      <p>
        <strong>Real-time analytics</strong> highlight placement rates and
        licensing progress so you can focus your efforts where they matter most.
      </p>
      <p>
        <strong>Automated outreach</strong> keeps students engaged while ensuring
        employers see the very best from your talent pipeline.
      </p>
      <p>
        We hope these features make connecting your students with employers a
        breeze. Thanks for helping them launch amazing careers!
      </p>
    </div>
  );
}

export default CareerStaffInfo;
