import React from 'react';
import styles from './Input.module.css';

const Input = React.forwardRef(({ error, className = '', disabled = false, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={`${styles.input} ${error ? styles.error : ''} ${className}`}
      aria-invalid={!!error}
      disabled={disabled}
      {...props}
    />
  );
});

export default Input;
