import React from 'react';

export function Input({ label, id, className = '', ...props }) {
  return (
    <div className={className}>
      {label && <label htmlFor={id} className="label-text">{label}</label>}
      <input id={id} className="input-field" {...props} />
    </div>
  );
}

export function Textarea({ label, id, rows = 4, className = '', ...props }) {
  return (
    <div className={className}>
      {label && <label htmlFor={id} className="label-text">{label}</label>}
      <textarea
        id={id}
        rows={rows}
        className="input-field resize-none"
        {...props}
      />
    </div>
  );
}

export function Select({ label, id, options = [], className = '', ...props }) {
  return (
    <div className={className}>
      {label && <label htmlFor={id} className="label-text">{label}</label>}
      <select id={id} className="input-field" {...props}>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}

export function Checkbox({ label, id, checked, onChange, className = '' }) {
  return (
    <label htmlFor={id} className={`flex items-center gap-2.5 cursor-pointer ${className}`}>
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={onChange}
        className="w-4 h-4 text-primary border-border rounded focus:ring-primary/20 cursor-pointer accent-primary"
      />
      <span className="text-sm text-text-primary">{label}</span>
    </label>
  );
}
