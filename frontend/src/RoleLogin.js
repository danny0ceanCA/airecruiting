import React from 'react';
import { useParams } from 'react-router-dom';
import LoginForm from './LoginForm';

const roleInfo = {
  career: (
    <>
      <h2>Career Services</h2>
      <p>TalentMatch AI empowers your department with holistic student profiles, AI-driven matching and instant reporting.</p>
    </>
  ),
  recruiter: (
    <>
      <h2>Recruiters</h2>
      <p>Find candidates who are more than just resumes using our AI-powered matching and custom insights.</p>
    </>
  ),
  applicant: (
    <>
      <h2>Job Seekers</h2>
      <p>Build a biography that tells your story and get matched to roles where you can thrive.</p>
    </>
  ),
};

function RoleLogin() {
  const { role } = useParams();
  return <LoginForm infoContent={roleInfo[role]} />;
}

export default RoleLogin;
