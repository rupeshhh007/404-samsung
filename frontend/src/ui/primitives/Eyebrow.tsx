import React from 'react';

interface EyebrowProps {
  readonly children: React.ReactNode;
  readonly className?: string;
}

export const Eyebrow: React.FC<EyebrowProps> = ({ children, className = '' }) => {
  return (
    <div
      className={`font-mono text-[11px] font-medium tracking-[0.16em] uppercase text-bone-500 select-none ${className}`}
    >
      {children}
    </div>
  );
};
