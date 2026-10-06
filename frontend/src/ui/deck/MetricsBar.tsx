import React, { useState, useRef, useEffect } from 'react';
import { formatMetricsViewModel } from '../viewmodel/metrics';
import type { MetricsProjection } from '../../api/types';

interface MetricsBarProps {
  readonly metrics: MetricsProjection | null;
  readonly className?: string;
}

export const MetricsBar: React.FC<MetricsBarProps> = ({ metrics, className = '' }) => {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { items, throughSequence, hasData } = formatMetricsViewModel(metrics);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setPopoverOpen(false);
      }
    };
    if (popoverOpen) {
      document.addEventListener('click', handleOutsideClick);
    }
    return () => document.removeEventListener('click', handleOutsideClick);
  }, [popoverOpen]);

  return (
    <div
      ref={containerRef}
      className={`relative h-10 px-4 bg-ink-950 border border-ink-600 flex items-center justify-between font-mono text-[11px] text-bone-500 select-none ${className}`}
    >
      {/* Metric Pairs Strip */}
      <div className="flex items-center gap-4 overflow-x-auto">
        {items.map((item, idx) => (
          <React.Fragment key={item.key}>
            {idx > 0 && <span className="text-ink-600">·</span>}
            <div className="flex items-center gap-1.5 whitespace-nowrap">
              <span className="uppercase tracking-wider">{item.label}</span>
              <span className="font-bold text-bone-300">{item.value}</span>
            </div>
          </React.Fragment>
        ))}
      </div>

      {/* Sequence & Popover Button */}
      <button
        type="button"
        onClick={() => setPopoverOpen((prev) => !prev)}
        aria-expanded={popoverOpen}
        className="ml-4 pl-3 border-l border-ink-600 font-mono text-[10px] text-bone-300 hover:text-bone-50 transition-colors uppercase whitespace-nowrap focus-visible:outline-sig-active"
      >
        <span>SNAPSHOT #{throughSequence}</span>
      </button>

      {/* Audit Popover with METRICS.md Formulas */}
      {popoverOpen && (
        <div
          role="tooltip"
          className="absolute bottom-12 right-0 z-50 w-80 p-4 bg-ink-850 border border-ink-600 slab-shadow text-bone-50 space-y-3 animate-fadeIn"
        >
          <div className="border-b border-ink-600 pb-2">
            <div className="font-mono text-xs font-bold uppercase tracking-wider text-bone-50">
              Session Metrics Audit
            </div>
            <div className="font-mono text-[10px] text-bone-500">
              Pinned to Journal Sequence #{throughSequence}
            </div>
          </div>

          <div className="space-y-2">
            {items.map((item) => (
              <div key={item.key} className="space-y-0.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-bone-300">{item.label}</span>
                  <span className="font-bold">{item.value}</span>
                </div>
                {item.formula && (
                  <div className="text-[10px] text-bone-600 font-mono">
                    {item.formula}
                  </div>
                )}
              </div>
            ))}
          </div>

          {!hasData && (
            <div className="text-bone-500 italic text-[11px]">
              No metrics measured yet
            </div>
          )}
        </div>
      )}
    </div>
  );
};
