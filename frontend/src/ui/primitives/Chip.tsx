import React from 'react';
import { Led, type LedStatus } from './Led';
import { Icon, type IconName } from './Icon';

export type SignalVariant =
  | 'active'
  | 'spec'
  | 'pending'
  | 'alarm'
  | 'adapt'
  | 'verify'
  | 'neutral'
  | 'slab';

interface ChipProps {
  readonly children: React.ReactNode;
  readonly variant?: SignalVariant;
  readonly dot?: boolean;
  readonly icon?: IconName;
  readonly dashed?: boolean;
  readonly className?: string;
  readonly title?: string;
}

const VARIANT_STYLES: Record<SignalVariant, string> = {
  active: 'border-sig-active/40 bg-sig-active/10 text-sig-active',
  spec: 'border-sig-spec/40 bg-sig-spec/10 text-sig-spec',
  pending: 'border-sig-pending/40 bg-sig-pending/10 text-sig-pending',
  alarm: 'border-sig-alarm/40 bg-sig-alarm/10 text-sig-alarm',
  adapt: 'border-sig-adapt/40 bg-sig-adapt/10 text-sig-adapt',
  verify: 'border-sig-verify/40 bg-sig-verify/10 text-sig-verify',
  neutral: 'border-ink-600 bg-ink-850 text-bone-300',
  slab: 'border-sig-pending bg-sig-pending text-ink-950 font-bold',
};

export const Chip: React.FC<ChipProps> = ({
  children,
  variant = 'neutral',
  dot = false,
  icon,
  dashed = false,
  className = '',
  title,
}) => {
  const borderStyle = dashed ? 'border-dashed' : 'border-solid';
  const variantClass = VARIANT_STYLES[variant] ?? VARIANT_STYLES.neutral;
  const ledStatus: LedStatus = variant === 'slab' ? 'pending' : variant;

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 h-6 px-2 font-mono text-[11px] uppercase tracking-wider border rounded-none select-none whitespace-nowrap ${borderStyle} ${variantClass} ${className}`}
    >
      {dot && <Led status={ledStatus} size={6} />}
      {icon && <Icon name={icon} size={12} />}
      <span>{children}</span>
    </span>
  );
};
