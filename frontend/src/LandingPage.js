import React from 'react';
import { Link } from 'react-router-dom';
import TopMenu from './TopMenu';
import logo from './logo.png';
import './LandingPage.css';

function LandingPage() {
  return (
    <div className="landing-container">
      <TopMenu />
      <img src={logo} className="landing-logo" alt="TalentMatch AI logo" />
      <h1 className="landing-title">Who Are You?</h1>
      <div className="landing-buttons">
        <Link to="/login" className="landing-btn">Career Services Login</Link>
        <Link to="/login" className="landing-btn">Recruiter</Link>
        <Link to="/login" className="landing-btn">Job Seekers</Link>
      </div>
    </div>
  );
}

export default LandingPage;
