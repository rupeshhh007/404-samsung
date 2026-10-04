import { useRef, useEffect } from 'react';

export interface StrandUniformsState {
  currentTension: number;
  targetTension: number;
  pulseProgress: number;
  pulseOrigin: [number, number];
  pointer: [number, number];
}

export function useStrandUniforms(targetTension: number) {
  const stateRef = useRef<StrandUniformsState>({
    currentTension: targetTension,
    targetTension,
    pulseProgress: 0,
    pulseOrigin: [0.5, 0.5],
    pointer: [0.5, 0.5],
  });

  useEffect(() => {
    stateRef.current.targetTension = targetTension;
  }, [targetTension]);

  const triggerPulse = (origin: [number, number] = [0.5, 0.5]) => {
    stateRef.current.pulseProgress = 0.01;
    stateRef.current.pulseOrigin = origin;
  };

  return { stateRef, triggerPulse };
}
