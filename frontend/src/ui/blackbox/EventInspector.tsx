import React from 'react';
import { Chip } from '../primitives/Chip';
import { CopyButton } from '../primitives/CopyButton';
import { JsonView } from './JsonView';
import { getEventRoleInfo } from '../viewmodel/eventRoles';
import { shortenId } from '../../utils/formatters';
import type { ProjectionEventMessage } from '../../api/types';

interface EventInspectorProps {
  readonly event: ProjectionEventMessage | null;
  readonly allEvents: readonly ProjectionEventMessage[];
  readonly onSelectSequence: (seq: number) => void;
}

export const EventInspector: React.FC<EventInspectorProps> = ({
  event,
  allEvents,
  onSelectSequence,
}) => {
  if (!event) {
    return (
      <div className="p-6 bg-ink-900 border border-ink-600 font-mono text-xs text-bone-500 text-center">
        Select an event bead to inspect causal evidence and projection delta.
      </div>
    );
  }

  const roleInfo = getEventRoleInfo(event.event_type);
  const correlationId = event.trace?.correlation_id ?? null;
  const eventId = (event as { event_id?: string }).event_id ?? null;

  // Affected collections from delta
  const changedCollections = Object.keys(event.projection_delta.changed ?? {}).sort();
  const removedCollections = Object.keys(event.projection_delta.removed ?? {}).sort();

  // Find causal chain: all events sharing the same correlation_id
  const causalChain = correlationId
    ? allEvents.filter((e) => e.trace?.correlation_id === correlationId)
    : [];

  return (
    <div className="space-y-4 font-mono text-xs bg-ink-900 border border-ink-600 p-4">
      {/* Event Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-600 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-bone-50 text-sm">
              {roleInfo.label}
            </span>
            <Chip variant={roleInfo.role} className="h-5 text-[9px]">
              #{event.sequence}
            </Chip>
          </div>
          <span className="text-bone-500 text-[10px] uppercase tracking-wider block mt-0.5">
            TYPE: {event.event_type}
          </span>
        </div>

        <Chip variant="neutral" className="h-6">
          LANE: {roleInfo.lane}
        </Chip>
      </div>

      {/* Identifiers & Correlation */}
      <div className="space-y-1.5 text-[11px]">
        {eventId && (
          <div className="flex items-center justify-between p-1.5 bg-ink-950 border border-ink-600">
            <span className="text-bone-500">EVENT ID</span>
            <div className="flex items-center gap-1.5">
              <span className="text-bone-300">{shortenId(eventId, 8, 6)}</span>
              <CopyButton text={eventId} label="Copy Event ID" />
            </div>
          </div>
        )}

        {correlationId && (
          <div className="flex items-center justify-between p-1.5 bg-ink-950 border border-ink-600">
            <span className="text-bone-500">CORRELATION ID</span>
            <div className="flex items-center gap-1.5">
              <span className="text-bone-300">{shortenId(correlationId, 8, 6)}</span>
              <CopyButton text={correlationId} label="Copy Correlation ID" />
            </div>
          </div>
        )}
      </div>

      {/* Affected Collections */}
      <div className="space-y-1">
        <div className="text-[10px] text-bone-500 uppercase tracking-wider">
          AFFECTED COLLECTIONS
        </div>
        <div className="flex flex-wrap gap-1.5">
          {changedCollections.map((col) => (
            <Chip key={col} variant="active" className="h-5 text-[9px]">
              {col}: updated
            </Chip>
          ))}
          {removedCollections.map((col) => (
            <Chip key={col} variant="alarm" className="h-5 text-[9px]">
              {col}: removed
            </Chip>
          ))}
          {changedCollections.length === 0 && removedCollections.length === 0 && (
            <span className="text-bone-600 text-[10px] italic">None</span>
          )}
        </div>
      </div>

      {/* Causal Chain Links */}
      {causalChain.length > 1 && (
        <div className="space-y-1.5 pt-2 border-t border-ink-600">
          <div className="text-[10px] text-bone-500 uppercase tracking-wider">
            CAUSAL CHAIN ({causalChain.length} EVENTS)
          </div>
          <div className="flex flex-wrap gap-1.5">
            {causalChain.map((chainEvt) => (
              <button
                key={chainEvt.sequence}
                type="button"
                onClick={() => onSelectSequence(chainEvt.sequence)}
                className={`px-2 py-0.5 border text-[10px] transition-colors focus-visible:outline-sig-active ${
                  chainEvt.sequence === event.sequence
                    ? 'border-bone-50 bg-bone-50 text-ink-950 font-bold'
                    : 'border-ink-600 bg-ink-950 text-bone-300 hover:border-bone-500'
                }`}
              >
                #{chainEvt.sequence} {chainEvt.event_type.slice(0, 10)}…
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Projection Delta JSON */}
      <div className="pt-2">
        <JsonView data={event.projection_delta} />
      </div>
    </div>
  );
};
