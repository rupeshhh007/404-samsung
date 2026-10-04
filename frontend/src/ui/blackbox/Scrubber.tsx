import React, { useEffect, useRef, useState } from 'react';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';

interface ScrubberProps {
  readonly currentSequence: number;
  readonly maxSequence: number;
  readonly onSequenceChange: (seq: number) => void;
  readonly onJumpToLive: () => void;
  readonly isLive: boolean;
  readonly disabled?: boolean;
}

export const Scrubber: React.FC<ScrubberProps> = ({
  currentSequence,
  maxSequence,
  onSequenceChange,
  onJumpToLive,
  isLive,
  disabled = false,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);

  const currentSequenceRef = useRef(currentSequence);
  currentSequenceRef.current = currentSequence;

  useEffect(() => {
    if (!isPlaying || disabled || maxSequence <= 1) return;

    const intervalMs = 400 / speed;
    const timer = setInterval(() => {
      const curr = currentSequenceRef.current;
      if (curr >= maxSequence) {
        setIsPlaying(false);
      } else {
        onSequenceChange(curr + 1);
      }
    }, intervalMs);

    return () => clearInterval(timer);
  }, [isPlaying, speed, maxSequence, disabled, onSequenceChange]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement)?.tagName)) return;

      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
        setIsPlaying((p) => !p);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const delta = e.shiftKey ? 5 : 1;
        onSequenceChange(Math.max(1, currentSequence - delta));
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        const delta = e.shiftKey ? 5 : 1;
        onSequenceChange(Math.min(maxSequence, currentSequence + delta));
      } else if (e.key === 'Home') {
        e.preventDefault();
        onSequenceChange(1);
      } else if (e.key === 'End') {
        e.preventDefault();
        onJumpToLive();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentSequence, maxSequence, onSequenceChange, onJumpToLive]);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-ink-900 border border-ink-600 font-mono text-xs select-none">
      {/* Playhead Controls */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setIsPlaying((p) => !p)}
          disabled={disabled || maxSequence <= 1}
          className="w-8 h-8 flex items-center justify-center bg-ink-850 border border-ink-600 hover:border-bone-500 text-bone-50 focus-visible:outline-sig-active disabled:opacity-40"
          title={isPlaying ? 'Pause replay (Space)' : 'Play replay (Space)'}
        >
          <Icon name={isPlaying ? 'pause' : 'play'} size={12} />
        </button>

        <button
          type="button"
          onClick={() => onSequenceChange(Math.max(1, currentSequence - 1))}
          disabled={disabled || currentSequence <= 1}
          className="w-8 h-8 flex items-center justify-center bg-ink-850 border border-ink-600 hover:border-bone-500 text-bone-50 focus-visible:outline-sig-active disabled:opacity-40"
          title="Previous event (←)"
        >
          <Icon name="rewind" size={12} />
        </button>

        <button
          type="button"
          onClick={() => onSequenceChange(Math.min(maxSequence, currentSequence + 1))}
          disabled={disabled || currentSequence >= maxSequence}
          className="w-8 h-8 flex items-center justify-center bg-ink-850 border border-ink-600 hover:border-bone-500 text-bone-50 focus-visible:outline-sig-active disabled:opacity-40"
          title="Next event (→)"
        >
          <Icon name="arrow-right" size={12} />
        </button>

        {/* Playback Speed Toggle */}
        <button
          type="button"
          onClick={() => setSpeed((s) => (s === 1 ? 2 : s === 2 ? 4 : 1))}
          className="h-8 px-2 border border-ink-600 bg-ink-850 text-bone-300 hover:text-bone-50 text-[10px] font-bold"
        >
          {speed}X
        </button>
      </div>

      {/* Sequence Scrubber Slider */}
      <div className="flex-1 min-w-[200px] flex items-center gap-3">
        <span className="text-[10px] text-bone-500">#1</span>
        <input
          type="range"
          min={1}
          max={Math.max(1, maxSequence)}
          value={currentSequence}
          onChange={(e) => onSequenceChange(parseInt(e.target.value, 10))}
          disabled={disabled}
          className="flex-1 accent-sig-active bg-ink-800 h-1.5 cursor-pointer disabled:opacity-40"
          aria-valuemin={1}
          aria-valuemax={maxSequence}
          aria-valuenow={currentSequence}
          aria-valuetext={`Journal Sequence #${currentSequence}`}
        />
        <span className="text-[10px] text-bone-500">#{maxSequence}</span>
      </div>

      {/* State & Jump to Live */}
      <div className="flex items-center gap-2">
        {!isLive && (
          <div className="px-2 py-1 bg-sig-pending/15 border border-sig-pending text-sig-pending text-[10px] font-bold tracking-wider">
            REWIND · #{currentSequence}
          </div>
        )}

        <Button
          variant={isLive ? 'ghost' : 'primary'}
          onClick={onJumpToLive}
          disabled={isLive || disabled}
          className="h-8 text-xs font-bold"
        >
          {isLive ? 'LIVE' : 'JUMP TO LIVE'}
        </Button>
      </div>
    </div>
  );
};
