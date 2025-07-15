import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import './TopMenu.css';

function TopMenu() {
  const [open, setOpen] = useState(false);

  return (
    <nav className={`top-menu${open ? ' open' : ''}`}> 
      <button className="menu-toggle" onClick={() => setOpen(!open)} aria-label="Toggle navigation">
        &#9776;
      </button>
      <div className="menu-links">
        <Link to="/login">Home</Link>
        <Link to="/about">About TalentMatch-AI</Link>
        <Link to="/about/applicants">Applicants</Link>
        <Link to="/about/career-service">Career Service</Link>
        <Link to="/about/recruiters">Recruiters</Link>
      </div>
    </nav>
  );
}

export default TopMenu;
