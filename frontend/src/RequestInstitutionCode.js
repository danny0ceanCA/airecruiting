import React from 'react';
import TopMenu from './TopMenu';

function RequestInstitutionCode() {
  return (
    <div className="info-container">
      <TopMenu />
      <h2>Request an Institutional Code</h2>
      <p>
        Please email <a href="mailto:support@talentmatch-ai.com">support@talentmatch-ai.com</a> to obtain your institutional code.
      </p>
    </div>
  );
}

export default RequestInstitutionCode;
