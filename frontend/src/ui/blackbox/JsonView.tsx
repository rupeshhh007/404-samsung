import React, { useState } from 'react';
import { CopyButton } from '../primitives/CopyButton';

interface JsonViewProps {
  readonly data: unknown;
  readonly className?: string;
  readonly defaultExpanded?: boolean;
}

export const JsonView: React.FC<JsonViewProps> = ({
  data,
  className = '',
  defaultExpanded = true,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const jsonString = JSON.stringify(data, null, 2);

  // Lightweight JSON tokenizer
  const renderHighlighted = (json: string) => {
    return json.split('\n').map((line, idx) => {
      // Keys: "key":
      const formatted = line
        .replace(/("[\w-]+")(?=\s*:)/g, '<span class="text-bone-300">$1</span>')
        // String values
        .replace(/:\s*(".*?")/g, ': <span class="text-sig-verify">$1</span>')
        // Numbers
        .replace(/:\s*(-?\d+\.?\d*)/g, ': <span class="text-sig-active">$1</span>')
        // Booleans and null
        .replace(/:\s*(true|false|null)/g, ': <span class="text-sig-pending font-bold">$1</span>');

      return (
        <div key={idx} dangerouslySetInnerHTML={{ __html: formatted }} />
      );
    });
  };

  return (
    <div className={`relative bg-ink-950 border border-ink-600 font-mono text-[11px] ${className}`}>
      <div className="flex items-center justify-between p-2 border-b border-ink-600 bg-ink-900 select-none">
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="text-bone-500 hover:text-bone-50 font-bold uppercase tracking-wider text-[10px] flex items-center gap-1.5 focus-visible:outline-sig-active"
        >
          <span>{expanded ? '[-]' : '[+]'}</span>
          <span>PROJECTION DELTA JSON</span>
        </button>
        <CopyButton text={jsonString} label="Copy JSON" />
      </div>

      {expanded && (
        <pre className="p-3 overflow-x-auto text-bone-300 max-h-72 leading-relaxed font-mono">
          {renderHighlighted(jsonString)}
        </pre>
      )}
    </div>
  );
};
