import React from 'react';
import { useParams } from 'react-router-dom';
import LoginForm from './LoginForm';

const roleInfo = {
  career: (
    <>
      <h2>Career Services Departments</h2>
      <p>
        Create student profiles by entering their training, credentials, and career goals.
      </p>
      <p>
        As recruiters post jobs, TalentMatch AI analyzes and matches your students to the most
        suitable roles.
      </p>
      <p>
        You’ll be able to track job activity, monitor which students are matched or assigned,
        and access real-time metrics to support program outcomes and reporting.
      </p>
    </>
  ),
  career_director: (
    <>
      <h2>Career Directors</h2>
      <p>
        Monitor outcomes across multiple partner programs and keep counselors aligned on outreach,
        student engagement, and placement goals.
      </p>
      <p>
        Review every approved student within your network, track assignments and placements, and
        study weekly performance metrics from a consolidated dashboard.
      </p>
      <p>
        Directors collaborate with individual career staff while maintaining a unified view of
        program impact.
      </p>
    </>
  ),
  recruiter: (
    <>
      <h2>Recruiters & Employers</h2>
      <p>
        Post your job by entering details such as credentials, certifications, and setting preferences.
      </p>
      <p>
        TalentMatch AI scans student profiles from partner schools and presents the best matches.
      </p>
      <p>
        You can review matched candidates, generate tailored resumes, and coordinate interviews
        with career services—all from a single platform.
      </p>
    </>
  ),
  applicant: (
    <>
      <h2>Students & Job Seekers</h2>
      <p>
        Quickly create your profile by adding your certifications, skills, and career goals.
      </p>
      <p>
        TalentMatch AI matches you to jobs that align with your background.
      </p>
      <p>
        When a recruiter expresses interest, you’ll receive an email letting you know you've been
        matched and that someone may contact you soon to schedule an interview.
      </p>
    </>
  ),
};



function RoleLogin() {
  const { role } = useParams();
  return <LoginForm infoContent={roleInfo[role]} />;
}

export default RoleLogin;
