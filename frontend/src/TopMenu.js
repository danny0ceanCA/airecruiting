import React from 'react';
import { Link } from 'react-router-dom';
import './TopMenu.css';

function TopMenu() {
  return (
    <nav className="top-menu">
      <Link to="/about">About TalentMatch-AI</Link>
      <Link to="/about/applicants">Applicants</Link>
      <Link to="/about/career-service">Career Service</Link>
      <Link to="/about/recruiters">Recruiters</Link>
    </nav>
  );
}

export default TopMenu;
