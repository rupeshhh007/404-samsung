import React, { useRef, useEffect, useState, useLayoutEffect } from 'react';
import { UserLine } from './UserLine';
import { AssistantLine } from './AssistantLine';
import { LockedLine } from './LockedLine';
import type { TranscriptItem } from '../viewmodel/transcript';
import type { ClaimProjection, EvidenceProjection } from '../../api/types';

interface TranscriptProps {
  readonly items: readonly TranscriptItem[];
  readonly allClaims: readonly ClaimProjection[];
  readonly allEvidence: readonly EvidenceProjection[];
  readonly pendingClaim?: ClaimProjection | null;
  readonly onRetryUserPrompt?: (text: string) => void;
}

export const Transcript: React.FC<TranscriptProps> = ({
  items,
  allClaims,
  allEvidence,
  pendingClaim,
  onRetryUserPrompt,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showScrollBottomChip, setShowScrollBottomChip] = useState(false);
  const userScrolledUpRef = useRef(false);

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior,
      });
      userScrolledUpRef.current = false;
      setShowScrollBottomChip(false);
    }
  };

  const handleScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom > 80) {
      userScrolledUpRef.current = true;
      setShowScrollBottomChip(true);
    } else {
      userScrolledUpRef.current = false;
      setShowScrollBottomChip(false);
    }
  };

  useLayoutEffect(() => {
    if (!userScrolledUpRef.current) {
      scrollToBottom('auto');
    }
  }, [items.length, pendingClaim]);

  return (
    <div className="relative flex-1 min-h-0 flex flex-col">
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        role="log"
        aria-live="off"
        className="flex-1 overflow-y-auto pr-3 space-y-1"
      >
        {items.length === 0 && !pendingClaim && (
          <div className="flex flex-col items-center justify-center h-full text-center p-8 text-bone-500 font-mono text-xs">
            <span className="text-bone-600 mb-1">// TRANSCRIPT EMPTY</span>
            <span>Issue an instruction below to begin interaction.</span>
          </div>
        )}

        {items.map((item) => {
          if (item.kind === 'user') {
            return (
              <UserLine
                key={`user-${item.id}`}
                item={item}
                onRetry={onRetryUserPrompt}
              />
            );
          }

          return (
            <AssistantLine
              key={`assistant-${item.id}`}
              speech={item.speech}
              allClaims={allClaims}
              allEvidence={allEvidence}
            />
          );
        })}

        {/* Tail Locked Words Line */}
        {pendingClaim && <LockedLine pendingClaim={pendingClaim} />}
      </div>

      {/* Floating '↓ New' Chip */}
      {showScrollBottomChip && (
        <button
          type="button"
          onClick={() => scrollToBottom('smooth')}
          className="absolute bottom-3 right-6 z-20 px-2.5 py-1 bg-ink-800 border border-sig-active text-sig-active font-mono text-[11px] uppercase tracking-wider slab-shadow animate-bounce flex items-center gap-1 focus-visible:outline-sig-active"
        >
          <span>↓ NEW</span>
        </button>
      )}
    </div>
  );
};
