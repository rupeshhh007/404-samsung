import React, { useMemo } from 'react';
import { getEventRoleInfo, type EventLane, type EventRole } from '../viewmodel/eventRoles';
import { shortenId } from '../../utils/formatters';
import type { ProjectionEventMessage } from '../../api/types';

interface StrandsProps {
  readonly events: readonly ProjectionEventMessage[];
  readonly onSelectSequence?: (sequence: number) => void;
  readonly className?: string;
}

const LANES: readonly EventLane[] = ['INTENT', 'EXECUTION', 'REALITY', 'VOICE'];

const ROLE_COLORS: Record<EventRole, string> = {
  active: '#4C8DFF',
  spec: '#A073FF',
  pending: '#FFB020',
  alarm: '#FF4438',
  adapt: '#19D3C5',
  verify: '#3DDC84',
  neutral: '#BDB5A7',
};

export const Strands: React.FC<StrandsProps> = ({
  events,
  onSelectSequence,
  className = '',
}) => {
  // Take last 24 events
  const recentEvents = useMemo(() => {
    return events.slice(-24);
  }, [events]);

  const laneY: Record<EventLane, number> = {
    SYSTEM: 15,
    INTENT: 40,
    EXECUTION: 68,
    REALITY: 95,
    VOICE: 122,
  };

  const totalWidth = 600;
  const leftGutter = 80;
  const usableWidth = totalWidth - leftGutter - 20;

  return (
    <div className={`relative bg-ink-900 border border-ink-600 p-3 select-none ${className}`}>
      <div className="flex items-center justify-between pb-2 font-mono text-[10px] text-bone-500 uppercase">
        <span>THE STRANDS // CAUSAL JOURNAL RECORDER</span>
        <span>LAST {recentEvents.length} EVENTS</span>
      </div>

      <div className="relative w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${totalWidth} 140`}
          className="w-full h-[140px] overflow-visible"
        >
          {/* Lane rails and labels */}
          {LANES.map((lane) => (
            <g key={lane}>
              {/* Lane label */}
              <text
                x={10}
                y={laneY[lane] + 4}
                className="font-mono text-[9px] fill-bone-500 uppercase tracking-widest font-semibold"
              >
                {lane}
              </text>
              {/* Rail Line */}
              <line
                x1={leftGutter}
                y1={laneY[lane]}
                x2={totalWidth}
                y2={laneY[lane]}
                stroke="#26221F"
                strokeWidth={1}
                strokeDasharray="2 3"
              />
            </g>
          ))}

          {/* Event beads */}
          {recentEvents.map((event, idx) => {
            const roleInfo = getEventRoleInfo(event.event_type);
            const y = laneY[roleInfo.lane] ?? 55;
            const step = recentEvents.length > 1 ? usableWidth / (recentEvents.length - 1) : 0;
            const x = leftGutter + idx * step;
            const color = ROLE_COLORS[roleInfo.role] ?? '#BDB5A7';

            const isDivergence = event.event_type === 'DivergenceDetected';
            const isResolved = event.event_type === 'DivergenceResolved';

            return (
              <g
                key={`bead-${event.sequence}`}
                className="cursor-pointer group"
                onClick={() => onSelectSequence?.(event.sequence)}
              >
                {/* Red tear across all lanes for DivergenceDetected */}
                {isDivergence && (
                  <path
                    d={`M ${x - 4} 10 L ${x + 4} 40 L ${x - 4} 70 L ${x + 4} 100 L ${x - 4} 130`}
                    fill="none"
                    stroke="#FF4438"
                    strokeWidth={2}
                    className="animate-pulse"
                  />
                )}

                {/* Green weld line across all lanes for DivergenceResolved */}
                {isResolved && (
                  <line
                    x1={x}
                    y1={10}
                    x2={x}
                    y2={130}
                    stroke="#3DDC84"
                    strokeWidth={2}
                  />
                )}

                {/* Bead outer glow */}
                <circle
                  cx={x}
                  cy={y}
                  r={7}
                  fill={color}
                  opacity={0.2}
                  className="group-hover:opacity-60 transition-opacity"
                />

                {/* Bead core */}
                <circle
                  cx={x}
                  cy={y}
                  r={4.5}
                  fill={color}
                  stroke="#0A0908"
                  strokeWidth={1.5}
                />

                {/* Tooltip title */}
                <title>
                  {`#${event.sequence} ${roleInfo.label} (${event.event_type})`}
                </title>
              </g>
            );
          })}
        </svg>

        {/* Screen Reader Equivalent */}
        <ol className="sr-only">
          {recentEvents.map((e) => (
            <li key={e.sequence}>
              {`Event ${e.sequence}: ${e.event_type}`}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
};
