import React from 'react';
import './AboutPanel.css';

function AboutPanel() {
  return (
    <div className="about-panel">
      <h2>About TalentMatch AI</h2>
      <p>
        TalentMatch AI leverages machine learning to match healthcare students and professionals with employers. Our technology analyzes your entire profile to deliver smarter, faster, and fairer hiring results.
      </p>

      <section>
        <h3>For Applicants</h3>
        <p><strong>Be Matched for Who You Are—Not Just a Resume</strong></p>
        <p>
          At TalentMatch AI, you're never reduced to a single page or just a list of skills. Instead, you build a professional biography that lets you share your story—your education, experience, goals, and what makes you unique. Our platform's AI sees the whole you, so you're matched with jobs that fit not just your background, but your ambitions too.
        </p>
        <p><strong>Here's how it works:</strong></p>
        <ul>
          <li><strong>Holistic Profile:</strong> Our guided questions help you tell your story, not just your job history.</li>
          <li><strong>AI Matching:</strong> When a new job is posted, our AI looks at your full biography and matches you to roles where you'll thrive.</li>
          <li><strong>Custom Resumes, Instantly:</strong> For every opportunity you match with, our technology generates a custom resume—tailored to each job and ready to send.</li>
          <li><strong>Personal Feedback:</strong> Download job descriptions highlighting your strengths and suggesting areas to grow.</li>
        </ul>
        <p>No more selling yourself or endlessly searching. With TalentMatch AI, you're seen for your whole story—matched, supported, and empowered to grow.</p>
      </section>

      <section>
        <h3>For Recruiters</h3>
        <p><strong>Find Talent That's More Than Just a Resume</strong></p>
        <p>
          TalentMatch AI goes beyond keywords and job boards. Our platform uses advanced AI to match you with healthcare candidates who are more than just lists of credentials—they're whole people with stories, potential, and real passion for the work.
        </p>
        <p><strong>Here's how it works:</strong></p>
        <ul>
          <li><strong>AI-Powered Matching:</strong> When you post a job, our AI reviews the entire pool of candidate biographies—not just their skills, but their interests, strengths, and aspirations.</li>
          <li><strong>Custom Resumes for Every Match:</strong> For each strong match, TalentMatch AI generates a custom resume tailored to your role.</li>
          <li><strong>See the Whole Candidate:</strong> Get a complete view including growth areas and strengths as analyzed by our platform.</li>
          <li><strong>Job Insights at a Glance:</strong> Download clear job match reports showing where candidates excel and why they're a strong fit.</li>
        </ul>
        <p>Spend less time sifting through generic applications, and more time connecting with candidates who are truly ready to succeed in your roles. With TalentMatch AI, hiring is smarter, faster, and built for real results.</p>
      </section>

      <section>
        <h3>For Career Services</h3>
        <p><strong>Empower Student Success—With Data, Insight, and Real Opportunity</strong></p>
        <p>
          TalentMatch AI is designed for career services teams that want more than just job postings. Our platform gives you the tools to support your students as whole people and deliver the outcomes your institution values most.
        </p>
        <p><strong>Here's how it works:</strong></p>
        <ul>
          <li><strong>Holistic Student Profiles:</strong> Students build rich biographies that showcase their unique backgrounds, strengths, and goals.</li>
          <li><strong>AI-Driven Matching:</strong> As employers post new roles, our AI matches your students based on who they are and where they're headed.</li>
          <li><strong>Custom Resumes and Actionable Feedback:</strong> For every match, the platform generates tailored resumes and job match reports highlighting strengths and areas for growth.</li>
          <li><strong>Instant Reporting:</strong> Monitor placement rates, match quality, and engagement in real time, and generate compliance reports with a click.</li>
        </ul>
        <p>With TalentMatch AI, you help students get discovered for their full potential—while easily meeting your department's reporting and success goals.</p>
      </section>
    </div>
  );
}

export default AboutPanel;
