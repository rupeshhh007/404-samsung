import React from 'react';

interface HairlineProps {
  readonly emphasis?: boolean;
  readonly vertical?: boolean;
  readonly className?: string;
}

export const Hairline: React.FC<HairlineProps> = ({
  emphasis = false,
  vertical = false,
  className = '',
}) => {
  const color = emphasis ? 'bg-bone-500/40' : 'bg-ink-600';
  const size = vertical ? 'w-px h-full' : 'h-px w-full';

  return <div className={`flex-shrink-0 ${color} ${size} ${className}`} aria-hidden="true" />;
};
