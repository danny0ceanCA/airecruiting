import React from 'react';
import './Tooltip.css';

function Tooltip({ text, children, position = 'top' }) {
  return (
    <span className="tooltip-container">
      {children}
      <span className={`tooltip tooltip-${position}`}>{text}</span>
    </span>
  );
}

export default Tooltip;
