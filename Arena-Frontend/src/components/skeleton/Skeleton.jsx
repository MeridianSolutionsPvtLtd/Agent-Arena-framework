import React from 'react';

/**
 * Primitive skeleton placeholder with smooth shimmer animation.
 */
export default function Skeleton({
  variant = 'rounded', // 'text' | 'circular' | 'rounded' | 'rectangular'
  width,
  height,
  className = '',
  style = {},
  ...props
}) {
  const variantStyles = {
    text: 'h-4 w-full rounded-md',
    circular: 'rounded-full shrink-0',
    rounded: 'rounded-2xl',
    rectangular: 'rounded-none',
  };

  const inlineStyles = {
    ...(width ? { width } : {}),
    ...(height ? { height } : {}),
    ...style,
  };

  return (
    <div
      className={`skeleton-shimmer ${variantStyles[variant] || 'rounded-2xl'} ${className}`}
      style={inlineStyles}
      aria-hidden="true"
      {...props}
    />
  );
}
