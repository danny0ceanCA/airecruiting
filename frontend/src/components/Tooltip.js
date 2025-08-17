import React from 'react';
import './Tooltip.css';

function Tooltip({ text, children }) {
  return (
    <span className="tooltip-container">
      {children}
      <span className="tooltip">{text}</span>
    </span>
  );
}

export default Tooltip;
