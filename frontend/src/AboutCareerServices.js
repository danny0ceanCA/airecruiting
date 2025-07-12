import React from 'react';
import TopMenu from './TopMenu';
import './InfoPage.css';

function AboutCareerServices() {
  return (
    <div className="info-container">
      <TopMenu />
      <h2>For Career Services</h2>
      <p><strong>Empower Student Success—With Data, Insight, and Real Opportunity</strong></p>
      <p>
        TalentMatch AI is designed for career services teams that want more than just job postings.
        Our platform gives you the tools to support your students as whole people and deliver the outcomes your institution values most.
      </p>
      <p><strong>Here’s how it works:</strong></p>
      <ul>
        <li><strong>Holistic Student Profiles:</strong> Students build rich biographies that showcase their unique backgrounds, strengths, and goals—not just a list of jobs.</li>
        <li><strong>AI-Driven Matching:</strong> As employers post new roles, our AI matches your students based on who they are and where they’re headed, ensuring better fit and better placement rates.</li>
        <li><strong>Custom Resumes and Actionable Feedback:</strong> For every match, the platform generates tailored resumes and job match reports—highlighting each student’s strengths, plus areas for further growth.</li>
        <li><strong>Instant Reporting:</strong> Monitor placement rates, match quality, and engagement in real time. Generate compliance and accreditation reports with just a click.</li>
      </ul>
      <p>
        With TalentMatch AI, you help students get discovered for their full potential—while easily meeting your department’s reporting and success goals.
      </p>
    </div>
  );
}

export default AboutCareerServices;
