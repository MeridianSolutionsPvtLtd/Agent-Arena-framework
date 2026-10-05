import React from 'react';

export default function Card({ children, className = '', hover = true, ...props }) {
  return (
    <div
      className={`
        bg-white rounded-xl border border-border p-6
        transition-shadow duration-200
        ${hover ? 'hover:shadow-lg hover:shadow-primary/5' : ''}
        ${className}
      `}
      {...props}
    >
      {children}
    </div>
  );
}
