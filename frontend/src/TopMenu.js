import React from 'react';
import { Link } from 'react-router-dom';
import './TopMenu.css';

function TopMenu() {
  return (
    <nav className="top-menu">
      <Link to="/">
        <span className="material-icons">home</span>
        Home
      </Link>
      <Link to="/about">
        <span className="material-icons">info</span>
        About TalentMatch-AI
      </Link>
      <Link to="/about/applicants">
        <span className="material-icons">person</span>
        Applicants
      </Link>
      <Link to="/about/career-service">
        <span className="material-icons">work</span>
        Career Service
      </Link>
      <Link to="/about/recruiters">
        <span className="material-icons">group</span>
        Recruiters
      </Link>
    </nav>
  );
}

export default TopMenu;
