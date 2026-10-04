import React, { useState, useMemo, useEffect } from 'react';
import { Recorder } from './Recorder';
import { Scrubber } from './Scrubber';
import { EventInspector } from './EventInspector';
import { InterlockBridge } from '../deck/InterlockBridge';
import { Odometer } from '../primitives/Odometer';
import { CopyButton } from '../primitives/CopyButton';
import { useTimeTravel } from './useTimeTravel';
import { deriveStage } from '../viewmodel/stage';
import { selectSessionSummary } from '../../state/projections';
import { shortenId } from '../../utils/formatters';
import type { ProjectionEventMessage, SessionProjection } from '../../api/types';

interface BlackBoxPageProps {
  readonly sessionId: string | null;
  readonly liveProjection: SessionProjection | null;
  readonly events: readonly ProjectionEventMessage[];
  readonly loading: boolean;
  readonly error: string | null;
}

export const BlackBoxPage: React.FC<BlackBoxPageProps> = ({
  sessionId,
  liveProjection,
  events,
  loading,
  error,
}) => {
  const { projectionsBySequence, isHistoryIncomplete, maxSequence } = useTimeTravel(
    sessionId,
    events,
  );

  const [selectedSequence, setSelectedSequence] = useState<number>(() => maxSequence || 1);

  // Sync selectedSequence to latest when new events arrive and user is at live
  useEffect(() => {
    if (maxSequence > 0 && selectedSequence >= maxSequence - 1) {
      setSelectedSequence(maxSequence);
    }
  }, [maxSequence]);

  const isLive = selectedSequence === maxSequence || maxSequence === 0;

  // Active projection at selected sequence (rewound or live)
  const activeProjection = useMemo(() => {
    if (isLive || !projectionsBySequence.has(selectedSequence)) {
      return liveProjection;
    }
    return projectionsBySequence.get(selectedSequence) ?? liveProjection;
  }, [isLive, selectedSequence, projectionsBySequence, liveProjection]);

  // Derive stage and gap for rewound state
  const stageInfo = useMemo(() => {
    return deriveStage(activeProjection, sessionId, 'CONNECTED');
  }, [activeProjection, sessionId]);

  // Selected event message
  const selectedEvent = useMemo(() => {
    return events.find((e) => e.sequence === selectedSequence) ?? events[events.length - 1] ?? null;
  }, [events, selectedSequence]);

  // Summary counts for odometer
  const summary = useMemo(() => {
    if (!activeProjection) {
      return { operation_count: 0, effect_count: 0, claim_count: 0, divergence_count: 0 };
    }
    return selectSessionSummary(activeProjection);
  }, [activeProjection]);

  if (!sessionId) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 font-mono text-xs text-bone-500 text-center">
        Start a session to record and scrub a causal journal trace.
      </div>
    );
  }

  return (
    <div className="flex-1 p-6 space-y-4 max-w-7xl mx-auto w-full select-none">
      {/* 1. Header Strip with Odometer Counters */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 bg-ink-900 border border-ink-600 font-mono text-xs">
        <div className="flex items-center gap-3">
          <span className="font-bold text-bone-50 uppercase tracking-wider text-sm">
            BLACK BOX FORENSICS
          </span>
          <span className="text-bone-500">
            SESS:{shortenId(sessionId, 6, 4)}
          </span>
          <CopyButton text={sessionId} label="Copy session ID" />
        </div>

        {/* 4 Odometer Counters */}
        <div className="flex items-center gap-6 text-[11px]">
          <div className="flex items-center gap-1.5">
            <span className="text-bone-500 uppercase">OPS:</span>
            <span className="text-bone-50 font-bold text-sm">
              <Odometer value={summary.operation_count} />
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-bone-500 uppercase">EFFECTS:</span>
            <span className="text-bone-50 font-bold text-sm">
              <Odometer value={summary.effect_count} />
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-bone-500 uppercase">CLAIMS:</span>
            <span className="text-bone-50 font-bold text-sm">
              <Odometer value={summary.claim_count} />
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-bone-500 uppercase">DIVERGENCES:</span>
            <span className="text-sig-alarm font-bold text-sm">
              <Odometer value={summary.divergence_count} />
            </span>
          </div>
        </div>
      </div>

      {/* History Notice if loading, incomplete, or error */}
      {loading && (
        <div className="p-2 bg-ink-850 border border-ink-600 font-mono text-xs text-bone-500 animate-pulse">
          Streaming retained events from server…
        </div>
      )}
      {isHistoryIncomplete && (
        <div className="p-2 bg-sig-pending/10 border border-sig-pending/40 font-mono text-xs text-sig-pending">
          Notice: History is incomplete (starts after sequence 1); time travel scrubbing is restricted.
        </div>
      )}
      {error && (
        <div className="p-2 bg-sig-alarm/10 border border-sig-alarm/40 font-mono text-xs text-sig-alarm">
          {error}
        </div>
      )}

      {/* 2. Full-Width Recorder Diagram */}
      <Recorder
        events={events}
        selectedSequence={selectedSequence}
        onSelectSequence={setSelectedSequence}
      />

      {/* 3. Sequence Scrubber with Keyboard & Playback Controls */}
      <Scrubber
        currentSequence={selectedSequence}
        maxSequence={maxSequence}
        onSequenceChange={setSelectedSequence}
        onJumpToLive={() => setSelectedSequence(maxSequence)}
        isLive={isLive}
        disabled={isHistoryIncomplete || events.length === 0}
      />

      {/* 4. Bottom Split: Left Inspector | Right State at #N */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: Event Inspector */}
        <EventInspector
          event={selectedEvent}
          allEvents={events}
          onSelectSequence={setSelectedSequence}
        />

        {/* Right: State at Sequence #N */}
        <div className="space-y-3 bg-ink-900 border border-ink-600 p-4">
          <div className="flex items-center justify-between border-b border-ink-600 pb-2 font-mono text-xs">
            <span className="font-bold text-bone-50 tracking-wider uppercase">
              STATE AT SEQUENCE #{selectedSequence}
            </span>
            {!isLive && (
              <span className="text-sig-pending font-bold text-[10px] uppercase">
                [REWOUND TIMELINE]
              </span>
            )}
          </div>

          <InterlockBridge
            stage={stageInfo.stage}
            gapPx={stageInfo.gapPx}
            projection={activeProjection}
            readOnly
          />
        </div>
      </div>
    </div>
  );
};

export default BlackBoxPage;
