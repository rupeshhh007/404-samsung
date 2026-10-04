import React from 'react';
import { Icon, type IconName } from './Icon';

export type ButtonVariant = 'primary' | 'ghost' | 'danger';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: ButtonVariant;
  readonly icon?: IconName;
  readonly iconRight?: IconName;
  readonly loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'ghost',
  icon,
  iconRight,
  loading = false,
  disabled = false,
  className = '',
  ...rest
}) => {
  const baseClasses =
    'relative inline-flex items-center justify-center gap-2 font-mono text-[12px] uppercase tracking-wider select-none transition-all rounded-none focus-visible:outline-2 focus-visible:outline-sig-active';

  let variantClasses = '';
  switch (variant) {
    case 'primary':
      variantClasses =
        'bg-bone-50 text-ink-950 font-bold px-5 h-12 slab-shadow hover:bg-white active:translate-x-[3px] active:translate-y-[3px] active:shadow-[3px_3px_0px_0px_var(--ink-950)] disabled:opacity-40 disabled:pointer-events-none';
      break;
    case 'danger':
      variantClasses =
        'bg-sig-alarm/10 border border-sig-alarm/40 text-sig-alarm px-4 h-9 hover:bg-sig-alarm/20 active:translate-y-px disabled:opacity-40 disabled:pointer-events-none';
      break;
    case 'ghost':
    default:
      variantClasses =
        'bg-transparent border border-ink-600 text-bone-300 px-4 h-9 hover:border-bone-500 hover:text-bone-50 hover:bg-ink-800 active:translate-y-px disabled:opacity-40 disabled:pointer-events-none';
      break;
  }

  return (
    <button
      disabled={disabled || loading}
      className={`${baseClasses} ${variantClasses} ${className}`}
      {...rest}
    >
      {loading ? (
        <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent animate-spin" />
      ) : (
        icon && <Icon name={icon} size={14} />
      )}
      <span>{children}</span>
      {!loading && iconRight && <Icon name={iconRight} size={14} />}
    </button>
  );
};
