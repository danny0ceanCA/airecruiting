import React from 'react';
import { Link } from 'react-router-dom';
import './TopMenu.css';
import Tooltip from './components/Tooltip';

function TopMenu() {
  return (
    <nav className="top-menu">
      <Link to="/">
        <Tooltip text="Home">
          <span className="material-icons">home</span>
        </Tooltip>
        Home
      </Link>
      <Link to="/about">
        <Tooltip text="About">
          <span className="material-icons">info</span>
        </Tooltip>
        About TalentMatch-AI
      </Link>
      <Link to="/about/applicants">
        <Tooltip text="Applicants">
          <span className="material-icons">person</span>
        </Tooltip>
        Applicants
      </Link>
      <Link to="/about/career-service">
        <Tooltip text="Career Service">
          <span className="material-icons">work</span>
        </Tooltip>
        Career Service
      </Link>
      <Link to="/about/recruiters">
        <Tooltip text="Recruiters">
          <span className="material-icons">group</span>
        </Tooltip>
        Recruiters
      </Link>
    </nav>
  );
}

export default TopMenu;
