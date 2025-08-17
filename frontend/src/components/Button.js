import React from 'react';
import styles from './Button.module.css';

const Button = ({ children, loading = false, disabled = false, className = '', ...props }) => {
  const isDisabled = disabled || loading;
  return (
    <button
      className={`${styles.button} ${isDisabled ? styles.disabled : ''} ${loading ? styles.loading : ''} ${className}`}
      disabled={isDisabled}
      aria-disabled={isDisabled}
      aria-busy={loading}
      {...props}
    >
      {loading ? 'Loading…' : children}
    </button>
  );
};

export default Button;
