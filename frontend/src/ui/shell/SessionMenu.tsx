import React, { useState, useRef, useEffect } from 'react';
import { CopyButton } from '../primitives/CopyButton';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { shortenId } from '../../utils/formatters';

interface SessionMenuProps {
  readonly sessionId: string | null;
  readonly lastAppliedSequence: number;
  readonly onNewSession: () => void;
  readonly onResetDemo: () => void;
  readonly actionPending?: boolean;
}

export const SessionMenu: React.FC<SessionMenuProps> = ({
  sessionId,
  lastAppliedSequence,
  onNewSession,
  onResetDemo,
  actionPending = false,
}) => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };

    const handleOutsideClick = (e: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('click', handleOutsideClick);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('click', handleOutsideClick);
    };
  }, [open]);

  return (
    <div className="relative inline-flex items-center">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="session-menu-trigger inline-flex h-7 items-center gap-1.5 border border-current bg-transparent px-2 font-mono text-[9px] uppercase tracking-wider opacity-60 transition-opacity hover:opacity-100"
      >
        <span>
          {sessionId ? `SESS:${shortenId(sessionId, 4, 3)}` : 'NO SESSION'}
        </span>
        <Icon name="chevron-down" size={10} className={open ? 'rotate-180' : ''} />
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="session-menu-popover absolute right-0 top-9 z-50 w-72 space-y-3 border border-ink-600 bg-ink-850 p-3 text-bone-50 shadow-2xl animate-fadeIn"
        >
          <div className="space-y-1">
            <div className="font-mono text-[10px] uppercase tracking-wider text-bone-500">
              Active Session
            </div>
            {sessionId ? (
              <div className="flex items-center justify-between gap-2 p-1.5 bg-ink-900 border border-ink-600">
                <span className="font-mono text-[11px] text-bone-300 truncate" title={sessionId}>
                  {sessionId}
                </span>
                <CopyButton text={sessionId} label="Copy session ID" />
              </div>
            ) : (
              <div className="font-mono text-xs text-bone-500">No session active</div>
            )}
          </div>

          <div className="flex items-center justify-between text-xs font-mono py-1 border-t border-b border-ink-600">
            <span className="text-bone-500">APPLIED SEQUENCE</span>
            <span className="text-bone-50 font-bold">#{lastAppliedSequence}</span>
          </div>

          <div className="flex flex-col gap-3 pt-1">
            <div>
              <Button
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                  onNewSession();
                }}
                disabled={actionPending}
                className="w-full text-xs"
              >
                New Session
              </Button>
              <span className="block font-sans text-[10px] text-bone-500 mt-1 px-0.5 leading-snug">
                New runtime session — external simulated world is preserved
              </span>
            </div>
            <div>
              <Button
                variant="danger"
                onClick={() => {
                  setOpen(false);
                  onResetDemo();
                }}
                disabled={actionPending || !sessionId}
                className="w-full text-xs"
              >
                Reset Demo State
              </Button>
              <span className="block font-sans text-[10px] text-bone-500 mt-1 px-0.5 leading-snug">
                Reset demo world + start clean session
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
