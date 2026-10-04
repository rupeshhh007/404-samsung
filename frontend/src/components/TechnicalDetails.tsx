import React from 'react';
import { Icons } from './Icons';
import { CopyButton } from './CopyButton';
import { shortenId } from '../utils/formatters';

export interface DetailItem {
  readonly label: string;
  readonly value: string | null | undefined;
  readonly fullValue?: string;
  readonly mono?: boolean;
}

interface TechnicalDetailsProps {
  readonly title?: string;
  readonly items?: readonly DetailItem[];
  readonly children?: React.ReactNode;
  readonly className?: string;
}

export const TechnicalDetails: React.FC<TechnicalDetailsProps> = ({
  title = 'Details',
  items,
  children,
  className = '',
}) => {
  return (
    <details className={`group text-xs text-stone-500 dark:text-stone-400 ${className}`}>
      <summary className="inline-flex cursor-pointer select-none items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-stone-400 hover:text-stone-800 dark:hover:text-stone-200 transition-colors list-none [&::-webkit-details-marker]:hidden">
        <Icons.ChevronDown className="w-3 h-3 transition-transform group-open:rotate-180 opacity-70" />
        <span>[{title}]</span>
      </summary>

      <div className="mt-2.5 space-y-1.5 border-l-2 border-stone-200 dark:border-stone-800 pl-3">
        {items && items.length > 0 && (
          <dl className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {items.map((item, idx) => {
              if (item.value === null || item.value === undefined) return null;
              const displayVal = item.value;
              const copyVal = item.fullValue ?? item.value;

              return (
                <div key={idx} className="flex flex-col min-w-0">
                  <dt className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500 font-mono">
                    {item.label}
                  </dt>
                  <dd className="flex items-center gap-1 text-[11px] text-stone-700 dark:text-stone-300">
                    <span
                      className={`truncate ${item.mono !== false ? 'font-mono' : ''}`}
                      title={copyVal}
                    >
                      {item.mono !== false && displayVal.length > 20
                        ? shortenId(displayVal, 8, 6)
                        : displayVal}
                    </span>
                    {copyVal && <CopyButton text={copyVal} label={`Copy ${item.label}`} />}
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
