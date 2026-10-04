import React, { useSyncExternalStore } from 'react';
import type { StoryboardClient } from './StoryboardClient';
import { Button } from '../../ui/primitives/Button';
import { Icon } from '../../ui/primitives/Icon';

interface StoryboardControlsProps {
  readonly client: StoryboardClient;
}

export const StoryboardControls: React.FC<StoryboardControlsProps> = ({ client }) => {
  // Listen to client updates
  useSyncExternalStore(
    (onStoreChange) => client.subscribe(onStoreChange),
    () => client.getSequence(),
  );

  const seq = client.getSequence();
  const total = client.getTotalSequences();
  const isPlaying = client.getIsPlaying();
  const speed = client.getPlaybackSpeed();
  const isContinuation = client.getIsScriptedContinuation();

  // Hidden when ?clean=1 is in URL
  const isClean =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('clean') === '1';

  if (isClean) {
    return null;
  }

  return (
    <aside
      aria-label="Storyboard controls"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 p-2 bg-ink-900/95 border border-ink-600 slab-shadow backdrop-blur-md text-xs font-mono select-none"
    >
      <div className="flex items-center gap-1.5 px-2 border-r border-ink-700">
        <span className="text-[10px] uppercase tracking-wider text-sig-pending font-bold">
          STORYBOARD
        </span>
        <span className="text-bone-400">
          #{seq} / #{total}
        </span>
        {isContinuation && (
          <span className="px-1 py-0.5 bg-sig-pending text-ink-950 text-[9px] font-bold uppercase tracking-wider">
            CONTINUATION
          </span>
        )}
      </div>

      {/* Prev */}
      <button
        type="button"
        onClick={() => client.stepBackward()}
        disabled={seq <= 0}
        title="Step back"
        className="px-2 py-1 bg-ink-800 hover:bg-ink-700 disabled:opacity-40 text-bone-200 border border-ink-600"
      >
        ◀
      </button>

      {/* Play/Pause */}
      <button
        type="button"
        onClick={() => client.togglePlay()}
        title={isPlaying ? 'Pause' : 'Play'}
        className="px-3 py-1 bg-sig-active text-ink-950 font-bold hover:brightness-110 border border-sig-active"
      >
        {isPlaying ? 'PAUSE' : 'PLAY'}
      </button>

      {/* Next */}
      <button
        type="button"
        onClick={() => client.stepForward()}
        disabled={seq >= total}
        title="Step forward"
        className="px-2 py-1 bg-ink-800 hover:bg-ink-700 disabled:opacity-40 text-bone-200 border border-ink-600"
      >
        ▶
      </button>

      {/* Speed Selector */}
      <div className="flex items-center gap-1 ml-2 border-l border-ink-700 pl-2">
        <span className="text-[10px] text-bone-500 uppercase">SPD:</span>
        {[0.5, 1, 2, 4].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => client.setSpeed(s)}
            className={`px-1.5 py-0.5 text-[10px] border ${
              speed === s
                ? 'bg-bone-50 text-ink-950 border-bone-50 font-bold'
                : 'bg-ink-800 text-bone-400 border-ink-600 hover:text-bone-200'
            }`}
          >
            {s}x
          </button>
        ))}
      </div>

      {/* Quick Jump buttons */}
      <div className="flex items-center gap-1 ml-2 border-l border-ink-700 pl-2">
        <button
          type="button"
          onClick={() => client.jumpTo(0)}
          title="Jump to Start"
          className="px-1.5 py-0.5 text-[10px] text-bone-400 hover:text-bone-100"
        >
          Reset
        </button>
        <button
          type="button"
          onClick={() => client.jumpTo(8)}
          title="Jump to Interrupt"
          className="px-1.5 py-0.5 text-[10px] text-bone-400 hover:text-bone-100"
        >
          #8 (Interrupt)
        </button>
        <button
          type="button"
          onClick={() => client.jumpTo(31)}
          title="Jump to Climax Start"
          className="px-1.5 py-0.5 text-[10px] text-bone-400 hover:text-bone-100"
        >
          #31 (Climax)
        </button>
        <button
          type="button"
          onClick={() => client.jumpTo(41)}
          title="Jump to Final Resolved"
          className="px-1.5 py-0.5 text-[10px] text-bone-400 hover:text-bone-100"
        >
          #41 (Resolved)
        </button>
      </div>
    </aside>
  );
};
