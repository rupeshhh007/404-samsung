import React from 'react';

export type LedStatus =
  | 'active'   // blue
  | 'spec'     // violet
  | 'pending'  // amber
  | 'alarm'    // red
  | 'adapt'    // teal
  | 'verify'   // green
  | 'neutral'  // bone/grey
  | 'idle';    // muted

interface LedProps {
  readonly status: LedStatus;
  readonly pulse?: boolean;
  readonly size?: number;
  readonly className?: string;
  readonly 'aria-label'?: string;
}

const COLOR_MAP: Record<LedStatus, { dot: string; glow: string }> = {
  active: { dot: 'bg-sig-active', glow: 'bg-sig-active/40' },
  spec: { dot: 'bg-sig-spec', glow: 'bg-sig-spec/40' },
  pending: { dot: 'bg-sig-pending', glow: 'bg-sig-pending/40' },
  alarm: { dot: 'bg-sig-alarm', glow: 'bg-sig-alarm/40' },
  adapt: { dot: 'bg-sig-adapt', glow: 'bg-sig-adapt/40' },
  verify: { dot: 'bg-sig-verify', glow: 'bg-sig-verify/40' },
  neutral: { dot: 'bg-bone-300', glow: 'bg-bone-300/30' },
  idle: { dot: 'bg-bone-600', glow: 'transparent' },
};

export const Led: React.FC<LedProps> = ({
  status,
  pulse = false,
  size = 8,
  className = '',
  'aria-label': ariaLabel,
}) => {
  const { dot, glow } = COLOR_MAP[status] ?? COLOR_MAP.neutral;

  return (
    <span
      className={`relative inline-flex items-center justify-center flex-shrink-0 ${className}`}
      style={{ width: size, height: size }}
      role="status"
      aria-label={ariaLabel}
    >
      {pulse && (
        <span
          className={`absolute inline-flex h-full w-full rounded-full animate-ping opacity-75 ${glow}`}
        />
      )}
      <span
        className={`relative inline-flex rounded-full ${dot}`}
        style={{ width: size, height: size }}
      />
    </span>
  );
};
