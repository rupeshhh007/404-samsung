import React, { useState, useMemo } from 'react';
import { getEventRoleInfo, type EventLane, type EventRole } from '../viewmodel/eventRoles';
import type { ProjectionEventMessage } from '../../api/types';

interface RecorderProps {
  readonly events: readonly ProjectionEventMessage[];
  readonly selectedSequence: number;
  readonly onSelectSequence: (seq: number) => void;
}

const LANES: readonly EventLane[] = ['INTENT', 'EXECUTION', 'REALITY', 'VOICE'];

const ROLE_COLORS: Record<EventRole, string> = {
  active: '#BDB5A7',
  spec: '#8A8377',
  pending: '#F4EFE6',
  alarm: '#C8321F',
  adapt: '#BDB5A7',
  verify: '#F4EFE6',
  neutral: '#BDB5A7',
};

export const Recorder: React.FC<RecorderProps> = ({
  events,
  selectedSequence,
  onSelectSequence,
}) => {
  const [filterText, setFilterText] = useState('');

  const laneY: Record<EventLane, number> = {
    SYSTEM: 25,
    INTENT: 55,
    EXECUTION: 85,
    REALITY: 115,
    VOICE: 145,
  };

  const eventSpacing = 32;
  const leftGutter = 90;
  const totalWidth = Math.max(800, leftGutter + events.length * eventSpacing + 40);

  const normalizedFilter = filterText.trim().toLowerCase();

  return (
    <div className="bg-ink-900 border border-ink-600 p-4 space-y-3 font-mono text-xs select-none">
      {/* Header and Filter */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-600 pb-2">
        <div className="flex items-center gap-3">
          <span className="font-bold text-bone-50 tracking-wider uppercase text-xs">
            FORENSIC RECORDER // ALL JOURNAL EVENTS ({events.length})
          </span>
          <span className="text-bone-500 text-[10px]">
            SELECTED: #{selectedSequence}
          </span>
        </div>

        {/* Filter Input (Dims non-matching beads) */}
        <div className="flex items-center gap-2">
          <span className="text-bone-500 text-[10px] uppercase">FILTER:</span>
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Event, lane, correlation..."
            className="h-7 px-2 bg-ink-950 border border-ink-600 text-bone-50 text-[11px] placeholder:text-bone-600 focus:outline-none focus:border-sig-active w-48"
          />
          {filterText && (
            <button
              type="button"
              onClick={() => setFilterText('')}
              className="text-bone-500 hover:text-bone-50 text-[10px]"
            >
              CLEAR
            </button>
          )}
        </div>
      </div>

      {/* Horizontally scrollable diagram */}
      <div className="overflow-x-auto relative max-h-[220px]">
        <svg
          width={totalWidth}
          height={180}
          viewBox={`0 0 ${totalWidth} 180`}
          className="overflow-visible"
        >
          {/* Sequence Ruler along top every 5 events */}
          {events.map((evt, idx) => {
            if (evt.sequence % 5 !== 0 && evt.sequence !== 1) return null;
            const x = leftGutter + idx * eventSpacing;

            return (
              <g key={`ruler-${evt.sequence}`}>
                <line
                  x1={x}
                  y1={5}
                  x2={x}
                  y2={15}
                  stroke="#4A443E"
                  strokeWidth={1}
                />
                <text
                  x={x}
                  y={22}
                  textAnchor="middle"
                  className="font-mono text-[9px] fill-bone-500"
                >
                  #{evt.sequence}
                </text>
              </g>
            );
          })}

          {/* Lane rails and labels */}
          {LANES.map((lane) => (
            <g key={lane}>
              <text
                x={10}
                y={laneY[lane] + 4}
                className="font-mono text-[9px] fill-bone-500 uppercase tracking-widest font-semibold"
              >
                {lane}
              </text>
              <line
                x1={leftGutter}
                y1={laneY[lane]}
                x2={totalWidth}
                y2={laneY[lane]}
                stroke="#26221F"
                strokeWidth={1}
                strokeDasharray="2 4"
              />
            </g>
          ))}

          {/* Event Beads */}
          {events.map((event, idx) => {
            const roleInfo = getEventRoleInfo(event.event_type);
            const y = laneY[roleInfo.lane] ?? 85;
            const x = leftGutter + idx * eventSpacing;
            const color = ROLE_COLORS[roleInfo.role] ?? '#BDB5A7';

            const isSelected = event.sequence === selectedSequence;
            const isDivergence = event.event_type === 'DivergenceDetected';
            const isResolved = event.event_type === 'DivergenceResolved';

            // Filter match check: dim non-matching beads
            const matchesFilter =
              !normalizedFilter ||
              event.event_type.toLowerCase().includes(normalizedFilter) ||
              roleInfo.label.toLowerCase().includes(normalizedFilter) ||
              roleInfo.lane.toLowerCase().includes(normalizedFilter) ||
              (event.trace?.correlation_id && event.trace.correlation_id.toLowerCase().includes(normalizedFilter)) ||
              String(event.sequence) === normalizedFilter;

            const opacity = matchesFilter ? 1.0 : 0.2;

            return (
              <g
                key={`rec-bead-${event.sequence}`}
                className="cursor-pointer group"
                onClick={() => onSelectSequence(event.sequence)}
                opacity={opacity}
              >
                {/* Active Playhead Indicator */}
                {isSelected && (
                  <line
                    x1={x}
                    y1={10}
                    x2={x}
                    y2={170}
                    stroke="#F4EFE6"
                    strokeWidth={1.5}
                    strokeDasharray="3 3"
                  />
                )}

                {/* Tear or Weld */}
                {isDivergence && (
                  <path
                    d={`M ${x - 3} 30 L ${x + 3} 70 L ${x - 3} 110 L ${x + 3} 150`}
                    fill="none"
                    stroke="#FF4438"
                    strokeWidth={2}
                  />
                )}
                {isResolved && (
                  <line
                    x1={x}
                    y1={30}
                    x2={x}
                    y2={160}
                    stroke="#3DDC84"
                    strokeWidth={2}
                  />
                )}

                {/* Bead */}
                <circle
                  cx={x}
                  cy={y}
                  r={isSelected ? 7 : 5}
                  fill={color}
                  stroke={isSelected ? '#F4EFE6' : '#0A0908'}
                  strokeWidth={isSelected ? 2 : 1}
                />

                <title>
                  {`#${event.sequence} ${roleInfo.label} (${event.event_type})`}
                </title>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
};
