import React, { useRef, useEffect, useState } from 'react';
import { gsap } from '../motion/gsap';
import { useReducedMotion } from '../motion/useReducedMotion';
import type { Stage } from '../viewmodel/stage';

interface CableProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly className?: string;
}

export const Cable: React.FC<CableProps> = ({ stage, gapPx, className = '' }) => {
  const pathRef = useRef<SVGPathElement>(null);
  const reducedMotion = useReducedMotion();

  const isDiverged = stage === 'DIVERGED';
  const isReconciling = stage === 'RECONCILING';

  useEffect(() => {
    if (reducedMotion || (!isDiverged && !isReconciling) || gapPx <= 10) return;

    let time = 0;
    const NUM_POINTS = 20;
    const amplitude = isDiverged ? 3.5 : 1.5;
    const frequency = 0.08;

    const onTick = () => {
      time += 1;
      const points: [number, number][] = [];

      for (let i = 0; i <= NUM_POINTS; i++) {
        const t = i / NUM_POINTS;
        const x = t * gapPx;
        // Standing wave with pinned ends at 0 and gapPx
        const envelope = Math.sin(t * Math.PI);
        const y = 20 + Math.sin(time * frequency + t * 4) * amplitude * envelope;
        points.push([x, y]);
      }

      if (points.length > 0 && pathRef.current) {
        let d = `M ${points[0]![0]} ${points[0]![1]}`;
        for (let i = 1; i < points.length; i++) {
          d += ` L ${points[i]![0]} ${points[i]![1]}`;
        }
        pathRef.current.setAttribute('d', d);
      }
    };

    gsap.ticker.add(onTick);
    return () => {
      gsap.ticker.remove(onTick);
    };
  }, [reducedMotion, isDiverged, isReconciling, gapPx]);

  if (gapPx <= 4) return null;

  const cableColor = isDiverged ? '#FF4438' : isReconciling ? '#19D3C5' : '#FFB020';

  return (
    <div
      className={`relative flex items-center justify-center select-none overflow-visible ${className}`}
      style={{ width: gapPx, height: 40 }}
      aria-hidden="true"
    >
      <svg
        width={gapPx}
        height={40}
        viewBox={`0 0 ${gapPx} 40`}
        className="overflow-visible"
      >
        {/* Glow filter */}
        <defs>
          <filter id="cable-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Cable Path */}
        <path
          ref={pathRef}
          d={`M 0 20 L ${gapPx} 20`}
          fill="none"
          stroke={cableColor}
          strokeWidth={isDiverged ? 2.5 : 1.5}
          strokeDasharray={isDiverged ? 'none' : '4 3'}
          filter={isDiverged ? 'url(#cable-glow)' : undefined}
        />
      </svg>

      {/* Mismatch badge at center if DIVERGED */}
      {isDiverged && (
        <div
          className="absolute z-10 w-6 h-6 bg-sig-alarm border border-bone-50 text-bone-50 flex items-center justify-center font-mono font-bold text-xs rotate-45 shadow-md"
          title="Divergence: Desired != Observed"
        >
          <span className="-rotate-45 select-none leading-none">≠</span>
        </div>
      )}
    </div>
  );
};
