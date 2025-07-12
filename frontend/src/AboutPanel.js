import React from 'react';
import TopMenu from './TopMenu';
import './InfoPage.css';

function AboutPanel() {
  return (
    <div className="info-container">
      <TopMenu />
      <h2>About TalentMatch-AI</h2>
      <p>
        TalentMatch-AI is a next-generation recruiting platform built for healthcare education. Our platform leverages cutting-edge artificial intelligence to transform how students, schools, and employers connect:
      </p>
      <ul>
        <li>
          <strong>Intelligent Job Matching:</strong> Our advanced AI looks far beyond keywords, considering each applicant’s education, skills, experience, goals, and location—so every match is relevant and meaningful.
        </li>
        <li>
          <strong>Custom Resume Creation:</strong> For every opportunity, our system automatically generates a personalized resume that showcases each candidate’s strengths for that specific role, ensuring applicants stand out.
        </li>
        <li>
          <strong>AI-Generated Job Descriptions & Guidance:</strong> We break down every job posting for applicants—clearly highlighting strengths, potential fit, and personalized suggestions for areas of improvement.
        </li>
        <li>
          <strong>Career Services Tracking & Reporting:</strong> Schools and career services staff get real-time placement metrics, detailed match tracking, and automated reports for accreditation and funding compliance—all in one place.
        </li>
        <li>
          <strong>Geographic Filtering:</strong> TalentMatch-AI matches candidates to positions not just by skills and interests, but also by geographic preferences—helping employers find local talent and applicants discover nearby opportunities.
        </li>
      </ul>
      <p>
        Our mission: Deliver intelligence with every placement—making healthcare hiring smarter, more personal, and built for real student and employer success.
      </p>
    </div>
  );
}

export default AboutPanel;
