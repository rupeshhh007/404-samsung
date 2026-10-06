import React, { useRef, useEffect } from 'react';
import { gsap } from '../motion/gsap';
import { useReducedMotion } from '../motion/useReducedMotion';

interface ScrambleProps {
  readonly text: string;
  readonly duration?: number;
  readonly chars?: string;
  readonly className?: string;
  readonly onComplete?: () => void;
}

export const Scramble: React.FC<ScrambleProps> = ({
  text,
  duration = 0.7,
  chars = '0123456789ABCDEF!#@',
  className = '',
  onComplete,
}) => {
  const elRef = useRef<HTMLSpanElement>(null);
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    if (!elRef.current) return;

    if (reducedMotion) {
      elRef.current.textContent = text;
      onComplete?.();
      return;
    }

    const tween = gsap.to(elRef.current, {
      duration,
      scrambleText: {
        text,
        chars,
        revealDelay: 0.1,
      },
      ease: 'none',
      onComplete: () => {
        if (elRef.current) {
          elRef.current.textContent = text; // guarantee exact text
        }
        onComplete?.();
      },
    });

    return () => {
      tween.kill();
      if (elRef.current) {
        elRef.current.textContent = text;
      }
    };
  }, [text, duration, chars, reducedMotion, onComplete]);

  return (
    <span
      ref={elRef}
      className={`inline-block font-mono ${className}`}
      aria-label={text}
    >
      {text}
    </span>
  );
};
