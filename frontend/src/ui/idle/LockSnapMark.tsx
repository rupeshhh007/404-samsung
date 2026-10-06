import React, { useRef, useEffect } from 'react';
import { gsap } from '../motion/gsap';
import { useReducedMotion } from '../motion/useReducedMotion';

interface LockSnapMarkProps {
  readonly size?: number;
  readonly className?: string;
}

export const LockSnapMark: React.FC<LockSnapMarkProps> = ({
  size = 120,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const squareRef = useRef<HTMLDivElement>(null);
  const circleRef = useRef<HTMLDivElement>(null);
  const seamFlashRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();

  const playSnapAnimation = () => {
    if (reducedMotion || !squareRef.current || !circleRef.current) return;

    const tl = gsap.timeline();

    // Reset initial positions
    tl.set(squareRef.current, { x: -40, opacity: 0 });
    tl.set(circleRef.current, { x: 40, opacity: 0 });
    if (seamFlashRef.current) {
      tl.set(seamFlashRef.current, { opacity: 0 });
    }

    // Slide in & mesh with lock ease
    tl.to([squareRef.current, circleRef.current], {
      x: 0,
      opacity: 1,
      duration: 0.7,
      ease: 'lock',
    });

    // 3-frame squash
    tl.to(containerRef.current, {
      scale: 0.94,
      duration: 0.08,
      ease: 'power1.in',
    });
    tl.to(containerRef.current, {
      scale: 1.04,
      duration: 0.08,
      ease: 'power1.out',
    });
    tl.to(containerRef.current, {
      scale: 1.0,
      duration: 0.12,
      ease: 'power2.out',
    });

    // Seam bone flash
    if (seamFlashRef.current) {
      tl.to(seamFlashRef.current, {
        opacity: 0.9,
        duration: 0.05,
      });
      tl.to(seamFlashRef.current, {
        opacity: 0,
        duration: 0.25,
        ease: 'power2.out',
      });
    }
  };

  useEffect(() => {
    playSnapAnimation();
  }, [reducedMotion]);

  const squareSize = size * 0.55;
  const circleSize = size * 0.55;

  return (
    <div
      ref={containerRef}
      onMouseEnter={playSnapAnimation}
      className={`relative inline-block cursor-pointer select-none flex-shrink-0 ${className}`}
      style={{ width: size, height: size }}
      title="INTERLOCK signature mark"
      aria-hidden="true"
    >
      {/* Bauhaus Square */}
      <div
        ref={squareRef}
        className="absolute top-0 left-0 border-4 border-bone-50 bg-ink-900/60"
        style={{ width: squareSize, height: squareSize }}
      />

      {/* Bauhaus Circle */}
      <div
        ref={circleRef}
        className="absolute bottom-0 right-0 rounded-full border-4 border-bone-50 bg-ink-900/60"
        style={{ width: circleSize, height: circleSize }}
      />

      {/* Seam Flash */}
      <div
        ref={seamFlashRef}
        className="absolute inset-0 bg-sig-verify/40 pointer-events-none opacity-0"
      />
    </div>
  );
};
