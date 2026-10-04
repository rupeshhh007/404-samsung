import React from 'react';
import { Icon } from './Icon';
import { CopyButton } from './CopyButton';
import { shortenId } from '../../utils/formatters';

export interface DetailItem {
  readonly label: string;
  readonly value: string | null | undefined;
  readonly fullValue?: string;
  readonly mono?: boolean;
}

interface DetailsProps {
  readonly title?: string;
  readonly items?: readonly DetailItem[];
  readonly children?: React.ReactNode;
  readonly className?: string;
  readonly defaultOpen?: boolean;
}

export const Details: React.FC<DetailsProps> = ({
  title = 'TECHNICAL DETAILS',
  items,
  children,
  className = '',
  defaultOpen = false,
}) => {
  return (
    <details
      open={defaultOpen}
      className={`group font-mono text-[11px] text-bone-500 ${className}`}
    >
      <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 uppercase tracking-widest text-bone-500 hover:text-bone-300 transition-colors list-none [&::-webkit-details-marker]:hidden">
        <Icon
          name="chevron-down"
          size={11}
          className="transition-transform group-open:rotate-180 opacity-70"
        />
        <span>{title}</span>
      </summary>

      <div className="mt-2.5 space-y-2 border-l border-ink-600 pl-3 py-1">
        {items && items.length > 0 && (
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {items.map((item, idx) => {
              if (item.value === null || item.value === undefined) return null;
              const displayVal = item.value;
              const copyVal = item.fullValue ?? item.value;

              return (
                <div key={idx} className="flex flex-col min-w-0">
                  <dt className="text-[10px] uppercase tracking-wider text-bone-500 font-mono">
                    {item.label}
                  </dt>
                  <dd className="flex items-center gap-1.5 text-[11px] text-bone-300">
                    <span
                      className={`truncate ${item.mono !== false ? 'font-mono' : ''}`}
                      title={copyVal}
                    >
                      {item.mono !== false && displayVal.length > 18
                        ? shortenId(displayVal, 6, 4)
                        : displayVal}
                    </span>
                    {copyVal && (
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
