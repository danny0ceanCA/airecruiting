import React from "react";
import AdminMenu from "./AdminMenu";

function CareerInfo() {
  const infoHtml = process.env.REACT_APP_CAREER_INFO_HTML || "";
  return (
    <div className="career-info">
      <AdminMenu />
      <div dangerouslySetInnerHTML={{ __html: infoHtml }} />
    </div>
  );
}

export default CareerInfo;
