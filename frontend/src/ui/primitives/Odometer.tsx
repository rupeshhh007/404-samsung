import React from 'react';
import { useReducedMotion } from '../motion/useReducedMotion';

interface OdometerProps {
  readonly value: string | number;
  readonly className?: string;
}

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

export const Odometer: React.FC<OdometerProps> = ({ value, className = '' }) => {
  const reducedMotion = useReducedMotion();
  const valueStr = String(value);

  return (
    <span
      className={`inline-flex items-center overflow-hidden font-display font-bold tabular ${className}`}
      aria-label={valueStr}
    >
      {valueStr.split('').map((char, index) => {
        const isDigit = char >= '0' && char <= '9';
        if (!isDigit) {
          return (
            <span key={`char-${index}`} className="inline-block" aria-hidden="true">
              {char}
            </span>
          );
        }

        const digitIndex = parseInt(char, 10);
        const translateY = `-${digitIndex * 10}%`;

        return (
          <span
            key={`col-${index}`}
            className="relative inline-block h-[1em] overflow-hidden"
            aria-hidden="true"
          >
            <span
              className="inline-flex flex-col leading-none"
              style={{
                transform: `translateY(${translateY})`,
                transition: reducedMotion
                  ? 'none'
                  : `transform 0.6s cubic-bezier(0.22, 1, 0.36, 1) ${index * 0.05}s`,
              }}
            >
              {DIGITS.map((d) => (
                <span key={d} className="h-[1em] flex items-center justify-center">
                  {d}
                </span>
              ))}
            </span>
          </span>
        );
      })}
    </span>
  );
};
