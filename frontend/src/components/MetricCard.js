import React from 'react';
import { Sparklines, SparklinesLine } from 'react-sparklines';
import './MetricCard.css';

function MetricCard({ title, value, data }) {
  const sparkData = data && data.length ? data : [0];

  return (
    <div className="metric-card">
      <div className="metric-card-header">
        <span className="metric-title">{title}</span>
        <span className="metric-value">{value}</span>
      </div>
      <Sparklines data={sparkData} width={100} height={20} margin={5}>
        <SparklinesLine color="#00BFFF" />
      </Sparklines>
    </div>
  );
}

export default MetricCard;
