import React, { useRef, useEffect, useState } from 'react';
import { Renderer, Program, Mesh, Triangle } from 'ogl';
import { vertexShader, fragmentShader } from './strandField.shader';
import { useReducedMotion } from '../motion/useReducedMotion';

interface StrandFieldProps {
  readonly tension?: number;
  readonly pulseProgress?: number;
  readonly pulseOrigin?: [number, number];
  readonly className?: string;
}

export const StrandField: React.FC<StrandFieldProps> = ({
  tension = 0,
  pulseProgress = 0,
  pulseOrigin = [0.5, 0.5],
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [webglFailed, setWebglFailed] = useState(false);
  const reducedMotion = useReducedMotion();

  const tensionRef = useRef(tension);
  const pulseRef = useRef(pulseProgress);
  const originRef = useRef(pulseOrigin);

  useEffect(() => {
    tensionRef.current = tension;
    pulseRef.current = pulseProgress;
    originRef.current = pulseOrigin;
  }, [tension, pulseProgress, pulseOrigin]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof window === 'undefined') return;

    let renderer: Renderer | null = null;
    let gl: WebGLRenderingContext | null = null;
    let animId = 0;
    let isContextLost = false;

    try {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      renderer = new Renderer({
        alpha: false,
        depth: false,
        antialias: false,
        dpr,
      });

      const gl = renderer.gl;
      if (!gl) {
        throw new Error('WebGL context not available');
      }

      const canvas = gl.canvas as HTMLCanvasElement;
      container.appendChild(canvas);

      const geometry = new Triangle(gl);
      const program = new Program(gl, {
        vertex: vertexShader,
        fragment: fragmentShader,
        uniforms: {
          uTime: { value: 0 },
          uRes: { value: [container.clientWidth, container.clientHeight] },
          uTension: { value: tensionRef.current },
          uCalm: { value: [0.3, 0.55, 1.0] },
          uAlarm: { value: [1.0, 0.27, 0.22] },
          uPulse: { value: 0 },
          uPulseOrigin: { value: [0.5, 0.5] },
          uPointer: { value: [0.5, 0.5] },
          uSeed: { value: 7.0 },
          uReduced: { value: reducedMotion ? 1.0 : 0.0 },
        },
      });

      const mesh = new Mesh(gl, { geometry, program });

      const handleResize = () => {
        if (!container || !renderer || isContextLost) return;
        const width = container.clientWidth;
        const height = container.clientHeight;
        renderer.setSize(width, height);
        program.uniforms.uRes.value = [width, height];
      };

      handleResize();
      window.addEventListener('resize', handleResize);

      // Pointer parallax tracking
      const handlePointer = (e: PointerEvent) => {
        if (reducedMotion || isContextLost) return;
        const rect = container.getBoundingClientRect();
        const px = (e.clientX - rect.left) / Math.max(1, rect.width);
        const py = 1.0 - (e.clientY - rect.top) / Math.max(1, rect.height);
        program.uniforms.uPointer.value = [px, py];
      };
      window.addEventListener('pointermove', handlePointer, { passive: true });

      // Context lost/restored handlers
      const handleContextLost = (e: Event) => {
        e.preventDefault();
        isContextLost = true;
        cancelAnimationFrame(animId);
      };
      const handleContextRestored = () => {
        isContextLost = false;
        renderLoop(0);
      };

      canvas.addEventListener('webglcontextlost', handleContextLost, false);
      canvas.addEventListener('webglcontextrestored', handleContextRestored, false);

      let currentTension = tensionRef.current;
      let lastTime = 0;

      const renderLoop = (time: number) => {
        if (isContextLost || document.hidden) {
          animId = requestAnimationFrame(renderLoop);
          return;
        }

        const delta = Math.min((time - lastTime) / 1000, 0.1);
        lastTime = time;

        // Smooth tension easing toward target
        currentTension += (tensionRef.current - currentTension) * Math.min(delta * 4, 1.0);

        program.uniforms.uTime.value = time * 0.001;
        program.uniforms.uTension.value = currentTension;
        program.uniforms.uPulse.value = pulseRef.current;
        program.uniforms.uPulseOrigin.value = originRef.current;
        program.uniforms.uReduced.value = reducedMotion ? 1.0 : 0.0;

        renderer?.render({ scene: mesh });

        if (reducedMotion) {
          // Render only once under reduced motion
          return;
        }

        animId = requestAnimationFrame(renderLoop);
      };

      animId = requestAnimationFrame(renderLoop);

      return () => {
        cancelAnimationFrame(animId);
        window.removeEventListener('resize', handleResize);
        window.removeEventListener('pointermove', handlePointer);
        canvas.removeEventListener('webglcontextlost', handleContextLost);
        canvas.removeEventListener('webglcontextrestored', handleContextRestored);
        if (canvas.parentNode === container) {
          container.removeChild(canvas);
        }
      };
    } catch {
      console.info('[INTERLOCK] WebGL context unavailable or disabled. Using static gradient fallback.');
      setWebglFailed(true);
    }
  }, [reducedMotion]);

  if (webglFailed) {
    return (
      <div
        className={`fixed inset-0 pointer-events-none z-0 bg-[radial-gradient(ellipse_at_center,_#151311_0%,_#0A0908_100%)] ${className}`}
        aria-hidden="true"
      />
    );
  }

  return (
    <div
      ref={containerRef}
      className={`fixed inset-0 pointer-events-none z-0 overflow-hidden ${className}`}
      aria-hidden="true"
    />
  );
};

export default StrandField;
