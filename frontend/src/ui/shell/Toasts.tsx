import React from 'react';
import { Icon } from '../primitives/Icon';

export interface ToastMessage {
  readonly id: string;
  readonly message: string;
  readonly kind?: 'error' | 'warning' | 'info';
  readonly onDismiss: () => void;
}

interface ToastsProps {
  readonly toasts: readonly ToastMessage[];
}

export const Toasts: React.FC<ToastsProps> = ({ toasts }) => {
  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-md w-full pointer-events-none"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((toast) => {
        const isError = toast.kind !== 'info' && toast.kind !== 'warning';
        const borderColor = isError ? 'border-l-sig-alarm' : 'border-l-sig-pending';

        return (
          <div
            key={toast.id}
            role="alert"
            className={`pointer-events-auto flex items-start gap-3 p-4 bg-ink-850 border border-ink-600 border-l-4 ${borderColor} slab-shadow text-bone-50`}
          >
            <Icon
              name="alert"
              size={18}
              className={`flex-shrink-0 mt-0.5 ${isError ? 'text-sig-alarm' : 'text-sig-pending'}`}
            />
            <div className="flex-1 min-w-0">
              <div className="font-mono text-[10px] tracking-wider uppercase text-bone-500 mb-0.5">
                {isError ? 'Runtime Notice' : 'Alert'}
              </div>
              <p className="font-sans text-xs text-bone-50 leading-relaxed break-words">
                {toast.message}
              </p>
            </div>
            <button
              type="button"
              onClick={toast.onDismiss}
              className="flex-shrink-0 p-1 text-bone-500 hover:text-bone-50 focus-visible:outline-sig-active"
              aria-label="Dismiss notification"
            >
              <Icon name="cross" size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
};
