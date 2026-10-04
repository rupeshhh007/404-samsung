import React from 'react';

export type IconName =
  | 'mark'
  | 'lock-closed'
  | 'lock-open'
  | 'lock-broken'
  | 'seal'
  | 'check'
  | 'cross'
  | 'alert'
  | 'arrow'
  | 'arrow-right'
  | 'chevron'
  | 'chevron-down'
  | 'copy'
  | 'terminal'
  | 'rewind'
  | 'play'
  | 'pause'
  | 'eye'
  | 'link'
  | 'stamp';

interface IconProps extends React.SVGProps<SVGSVGElement> {
  readonly name: IconName;
  readonly size?: number | string;
  readonly className?: string;
}

export const Icon: React.FC<IconProps> = ({
  name,
  size = 16,
  className = '',
  ...rest
}) => {
  const commonProps = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.75,
    strokeLinecap: 'square' as const,
    strokeLinejoin: 'miter' as const,
    className,
    'aria-hidden': true,
    ...rest,
  };

  switch (name) {
    case 'mark':
      return (
        <svg {...commonProps} viewBox="0 0 24 24">
          {/* Bauhaus signature: square and circle overlapping */}
          <rect x="3" y="3" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.75" />
          <circle cx="15.5" cy="15.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      );

    case 'lock-closed':
      return (
        <svg {...commonProps}>
          <rect x="5" y="11" width="14" height="10" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
      );

    case 'lock-open':
      return (
        <svg {...commonProps}>
          <rect x="5" y="11" width="14" height="10" />
          <path d="M8 11V7a4 4 0 0 1 8 0v1" />
        </svg>
      );

    case 'lock-broken':
      return (
        <svg {...commonProps}>
          <rect x="5" y="11" width="14" height="10" />
          <path d="M8 11V7a4 4 0 0 1 8 0" />
          <line x1="2" y1="2" x2="22" y2="22" stroke="currentColor" strokeWidth="1.75" />
        </svg>
      );

    case 'seal':
      return (
        <svg {...commonProps}>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 7v5l3 2" />
        </svg>
      );

    case 'check':
      return (
        <svg {...commonProps}>
          <polyline points="4 12 9 17 20 6" />
        </svg>
      );

    case 'cross':
      return (
        <svg {...commonProps}>
          <line x1="5" y1="5" x2="19" y2="19" />
          <line x1="19" y1="5" x2="5" y2="19" />
        </svg>
      );

    case 'alert':
      return (
        <svg {...commonProps}>
          <polygon points="12 3 22 21 2 21" />
          <line x1="12" y1="9" x2="12" y2="14" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      );

    case 'arrow':
    case 'arrow-right':
      return (
        <svg {...commonProps}>
          <line x1="4" y1="12" x2="20" y2="12" />
          <polyline points="14 6 20 12 14 18" />
        </svg>
      );

    case 'chevron':
    case 'chevron-down':
      return (
        <svg {...commonProps}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      );

    case 'copy':
      return (
        <svg {...commonProps}>
          <rect x="9" y="9" width="11" height="11" />
          <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
        </svg>
      );

    case 'terminal':
      return (
        <svg {...commonProps}>
          <polyline points="4 6 10 12 4 18" />
          <line x1="12" y1="18" x2="20" y2="18" />
        </svg>
      );

    case 'rewind':
      return (
        <svg {...commonProps}>
          <polygon points="11 19 2 12 11 5 11 19" fill="currentColor" />
          <polygon points="22 19 13 12 22 5 22 19" fill="currentColor" />
        </svg>
      );

    case 'play':
      return (
        <svg {...commonProps}>
          <polygon points="6 4 20 12 6 20 6 4" fill="currentColor" />
        </svg>
      );

    case 'pause':
      return (
        <svg {...commonProps}>
          <rect x="6" y="4" width="4" height="16" fill="currentColor" />
          <rect x="14" y="4" width="4" height="16" fill="currentColor" />
        </svg>
      );

    case 'eye':
      return (
        <svg {...commonProps}>
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );

    case 'link':
      return (
        <svg {...commonProps}>
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      );

    case 'stamp':
      return (
        <svg {...commonProps}>
          <rect x="3" y="15" width="18" height="6" />
          <path d="M7 15V9a5 5 0 0 1 10 0v6" />
          <line x1="12" y1="3" x2="12" y2="4" />
        </svg>
      );

    default:
      return null;
  }
};
