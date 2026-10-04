import { useEffect, useRef } from 'react';
import { detectCues, type CueEvent } from './cues';
import { useLiveAnnouncement } from '../../shell/LiveRegions';
import { useReducedMotion } from '../useReducedMotion';
import type { SessionProjection } from '../../../api/types';

interface StageDirectorOptions {
  readonly onCue?: (cue: CueEvent) => void;
  readonly isStale?: boolean;
}

export function useStageDirector(
  projection: SessionProjection | null,
  sessionId: string | null,
  options: StageDirectorOptions = {},
) {
  const { announcePolite, announceAssertive } = useLiveAnnouncement();
  const reducedMotion = useReducedMotion();

  const prevProjectionRef = useRef<SessionProjection | null>(null);
  const prevSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Detect transitions
    const cues = detectCues(
      prevProjectionRef.current,
      projection,
      prevSessionIdRef.current,
      sessionId,
    );

    // Update refs for next transition
    prevProjectionRef.current = projection;
    prevSessionIdRef.current = sessionId;

    // Dispatch announcements and notifications
    for (const cue of cues) {
      if (cue.announcement) {
        if (cue.announcement.type === 'assertive') {
          announceAssertive(cue.announcement.message);
        } else {
          announcePolite(cue.announcement.message);
        }
      }

      if (!reducedMotion) {
        options.onCue?.(cue);
      }
    }
  }, [projection, sessionId, reducedMotion, announcePolite, announceAssertive]);
}
