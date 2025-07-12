import React from 'react';
import TopMenu from './TopMenu';
import './InfoPage.css';

function AboutRecruiters() {
  return (
    <div className="info-container">
      <TopMenu />
      <h2>For Recruiters</h2>
      <p><strong>Find Talent That’s More Than Just a Resume</strong></p>
      <p>
        TalentMatch AI goes beyond keywords and job boards. Our platform uses advanced AI to match you with healthcare candidates who are more than just lists of credentials—they’re whole people with stories, potential, and real passion for the work.
      </p>
      <p><strong>Here’s how it works:</strong></p>
      <p><strong>AI-Powered Matching:</strong> When you post a job, our AI instantly reviews the entire pool of candidate biographies—not just their skills, but their interests, strengths, and aspirations.</p>
      <p><strong>Custom Resumes for Every Match:</strong> For each strong match, TalentMatch AI generates a custom resume tailored to your role, so you see exactly how each candidate’s background aligns with your needs.</p>
      <p><strong>See the Whole Candidate:</strong> You don’t just get bullet points—you get a complete view, including a candidate’s growth areas and strengths, as analyzed by our platform.</p>
      <p><strong>Job Insights at a Glance:</strong> Download clear job match reports for each candidate, showing where they excel, areas for development, and why they’re a strong fit.</p>
      <p>
        Spend less time sifting through generic applications, and more time connecting with candidates who are truly ready to succeed in your roles.
      </p>
      <p>
        With TalentMatch AI, hiring is smarter, faster, and built for real results.
      </p>
    </div>
  );
}

export default AboutRecruiters;
