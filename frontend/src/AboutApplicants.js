import React from 'react';
import TopMenu from './TopMenu';
import './InfoPage.css';

function AboutApplicants() {
  return (
    <div className="info-container">
      <TopMenu />
      <h2>For Applicants</h2>
      <p><strong>Be Matched for Who You Are—Not Just a Resume</strong></p>
      <p>
        At TalentMatch AI, you're never reduced to a single page or just a list of skills.
        Instead, you build a professional biography that lets you share your story—your education,
        experience, goals, and what makes you unique. Our platform's AI sees the whole you,
        so you're matched with jobs that fit not just your background, but your ambitions too.
      </p>
      <p><strong>Here's how it works:</strong></p>
      <ul>
        <li><strong>Holistic Profile:</strong> Our guided questions help you tell your story, not just your job history.</li>
        <li><strong>AI Matching:</strong> When a new job is posted, our AI looks at your full biography and matches you to roles where you'll thrive.</li>
        <li><strong>Custom Resumes, Instantly:</strong> For every opportunity you match with, our technology generates a custom resume—tailored to each job and ready to send (no more "one-size-fits-all" resumes).</li>
        <li><strong>Personal Feedback:</strong> For every job match, you can download a job description that highlights your strengths and suggests areas where you could grow—so you always know how you fit and where you can improve.</li>
      </ul>
      <p>
        No more selling yourself or endlessly searching. With TalentMatch AI, you're seen for your whole story—matched, supported, and empowered to grow.
      </p>
    </div>
  );
}

export default AboutApplicants;
