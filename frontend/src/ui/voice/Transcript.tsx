import React, { useRef, useState, useLayoutEffect } from 'react';
import { UserLine } from './UserLine';
import { AssistantLine } from './AssistantLine';
import { LockedLine } from './LockedLine';
import type { TranscriptItem } from '../viewmodel/transcript';
import type { ClaimProjection, EvidenceProjection } from '../../api/types';

interface TranscriptProps {
  readonly items: readonly TranscriptItem[];
  readonly allClaims?: readonly ClaimProjection[];
  readonly allEvidence?: readonly EvidenceProjection[];
  readonly pendingClaim?: ClaimProjection | null;
  readonly interlude?: React.ReactNode;
  readonly supportingLine?: string | null;
  readonly onRetryUserPrompt?: (text: string) => void;
}

export const Transcript: React.FC<TranscriptProps> = ({
  items,
  pendingClaim,
  interlude,
  supportingLine,
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

  const latestUserSequence = items.reduce((sequence, item) =>
    item.kind === 'user' ? Math.max(sequence, item.sequence ?? sequence) : sequence, -1);
  const newestUncertainty = items.reduce<TranscriptItem | null>((latest, item) => {
    if (item.kind !== 'assistant' || item.speech.act_type !== 'UNCERTAINTY' ||
        !item.speech.rendered_text || (item.speech.approved_through_sequence ?? -1) < latestUserSequence ||
        item.speech.state === 'CANCELLED' || item.speech.state === 'BLOCKED') return latest;
    if (!latest || latest.kind !== 'assistant' ||
        (item.speech.approved_through_sequence ?? -1) >= (latest.speech.approved_through_sequence ?? -1)) return item;
    return latest;
  }, null);

  return (
    <div className="editorial-transcript relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        role="log"
        aria-live="off"
        className="flex-1"
      >
        {items.length === 0 && !pendingClaim && (
          <div className="mb-12 max-w-xl font-voice text-4xl leading-tight text-[var(--console-ink)]">
            <span>What should reality do next?</span>
          </div>
        )}

        {items.map((item, index) => {
          const showInterlude = interlude && item.kind === 'assistant' &&
            !items.slice(0, index).some((candidate) => candidate.kind === 'assistant');
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
            <React.Fragment key={`assistant-${item.id}`}>
              {showInterlude && interlude}
              <AssistantLine speech={item.speech} supportingLine={item === newestUncertainty ? supportingLine : null} />
            </React.Fragment>
          );
        })}

        {interlude && !items.some((item) => item.kind === 'assistant') && interlude}

        {/* Tail Pending Status Line */}
        {pendingClaim && <LockedLine />}
      </div>

      {/* Floating '↓ New' Chip */}
      {showScrollBottomChip && (
        <button
          type="button"
          onClick={() => scrollToBottom('smooth')}
          className="absolute bottom-3 right-4 px-3 py-1 bg-ink-800 border border-ink-600 text-bone-200 font-mono text-xs shadow-lg hover:bg-ink-700"
        >
          ↓ New
        </button>
      )}
    </div>
  );
};
