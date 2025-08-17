import React from 'react';
import './Skeleton.css';

function Skeleton({ className = '', style = {} }) {
  return <div className={`skeleton ${className}`} style={style} />;
}

export default Skeleton;
