import React from 'react';
import { Icons } from './Icons';
import { CopyButton } from './CopyButton';
import { shortenId } from '../utils/formatters';

export interface DetailItem {
  readonly label: string;
  readonly value: string | null | undefined;
  readonly fullValue?: string;
  readonly copyable?: boolean;
  readonly mono?: boolean;
}

interface TechnicalDetailsProps {
  readonly title?: string;
  readonly items?: readonly DetailItem[];
  readonly children?: React.ReactNode;
  readonly className?: string;
  readonly defaultOpen?: boolean;
}

export const TechnicalDetails: React.FC<TechnicalDetailsProps> = ({
  title = 'Protocol details',
  items,
  children,
  className = '',
  defaultOpen = false,
}) => {
  return (
    <details
      className={`group border-t border-stone-200/60 dark:border-stone-800/60 pt-2.5 mt-3 ${className}`}
      open={defaultOpen ? true : undefined}
    >
      <summary className="flex cursor-pointer select-none items-center gap-1.5 text-[11px] font-medium tracking-wide text-stone-500 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200 transition-colors list-none [&::-webkit-details-marker]:hidden">
        <Icons.ChevronDown className="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-180 opacity-70" />
        <span>{title}</span>
      </summary>

      <div className="mt-2.5 space-y-1.5 text-xs">
        {items && items.length > 0 && (
          <dl className="grid grid-cols-1 gap-1.5 rounded-lg bg-stone-100/70 p-2.5 dark:bg-stone-900/60 sm:grid-cols-2">
            {items.map((item, idx) => {
              if (item.value === null || item.value === undefined) return null;
              const displayVal = item.value;
              const copyVal = item.fullValue ?? item.value;

              return (
                <div key={idx} className="flex flex-col gap-0.5 min-w-0">
                  <dt className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                    {item.label}
                  </dt>
                  <dd className="flex items-center gap-1 text-[11px] text-stone-700 dark:text-stone-300">
                    <span
                      className={`truncate ${
                        item.mono !== false ? 'font-mono' : ''
                      }`}
                      title={copyVal}
                    >
                      {item.mono !== false && displayVal.length > 20
                        ? shortenId(displayVal, 8, 6)
                        : displayVal}
                    </span>
                    {item.copyable !== false && copyVal && (
                      <CopyButton text={copyVal} label={`Copy ${item.label}`} />
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
        {children}
      </div>
    </details>
  );
};
