import React, { useState, useEffect } from 'react';
import { LockSnapMark } from './LockSnapMark';
import { PillarRow } from './PillarRow';
import { Button } from '../primitives/Button';
import { Eyebrow } from '../primitives/Eyebrow';
import { Hairline } from '../primitives/Hairline';
import { useFontsReady } from '../motion/useFontsReady';

interface IdleScreenProps {
  readonly onBeginSession: () => Promise<boolean>;
  readonly onRunRace: () => void;
  readonly onHealthCheck: () => Promise<boolean>;
  readonly baseUrl: string;
}

export const IdleScreen: React.FC<IdleScreenProps> = ({
  onBeginSession,
  onRunRace,
  onHealthCheck,
  baseUrl,
}) => {
  const [healthStatus, setHealthStatus] = useState<'checking' | 'ok' | 'error'>('checking');
  const [loading, setLoading] = useState(false);
  const fontsReady = useFontsReady();

  const checkHealth = async () => {
    setHealthStatus('checking');
    try {
      const ok = await onHealthCheck();
      setHealthStatus(ok ? 'ok' : 'error');
    } catch {
      setHealthStatus('error');
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  const handleBegin = async () => {
    setLoading(true);
    try {
      await onBeginSession();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-[calc(100vh-64px)] flex flex-col justify-between p-8 md:p-14 lg:p-16 max-w-7xl mx-auto w-full z-10">
      {/* Top / Main Hero Content */}
      <div className="flex flex-col justify-center my-auto space-y-10 max-w-5xl">
        <div className="flex flex-col items-start gap-4">
          {/* Signature Bauhaus Mark */}
          <LockSnapMark size={110} />

          {/* Machine Eyebrow */}
          <Eyebrow className="mt-2 text-bone-500">
            SYSTEM CORE // DETERMINISTIC AGENT CONSISTENCY
          </Eyebrow>

          {/* Giant Title */}
          <h1
            className={`font-display font-extrabold uppercase tracking-[-0.02em] text-bone-50 leading-[0.85] text-[clamp(64px,11vw,180px)] select-none transition-opacity duration-500 ${
              fontsReady ? 'opacity-100' : 'opacity-80'
            }`}
          >
            INTERLOCK
          </h1>
        </div>

        {/* Cinematic Tagline with Pillar Highlights */}
        <div className="space-y-4">
          <p className="font-voice italic text-[clamp(24px,2.8vw,42px)] text-bone-50 leading-[1.25]">
            Anticipate early. Commit safely. Speak only what reality confirms.
          </p>

          {/* Three Pillar Accent Lines */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 pt-2 max-w-3xl">
            <div className="space-y-1">
              <span className="font-mono text-[10px] tracking-widest text-sig-spec font-bold">
                01 // ANTICIPATE
              </span>
              <div className="h-0.5 w-full bg-sig-spec/70" />
            </div>
            <div className="space-y-1">
              <span className="font-mono text-[10px] tracking-widest text-sig-adapt font-bold">
                02 // ADAPT
              </span>
              <div className="h-0.5 w-full bg-sig-adapt/70" />
            </div>
            <div className="space-y-1">
              <span className="font-mono text-[10px] tracking-widest text-sig-verify font-bold">
                03 // VERIFY
              </span>
              <div className="h-0.5 w-full bg-sig-verify/70" />
            </div>
          </div>
        </div>

        {/* Action Controls & Health Status */}
        <div className="space-y-4 pt-4">
          <div className="flex flex-wrap items-center gap-4">
            <Button
              variant="primary"
              onClick={handleBegin}
              loading={loading}
              iconRight="arrow-right"
              className="h-16 px-8 text-sm font-extrabold"
            >
              Begin Session
            </Button>

            <Button
              variant="ghost"
              onClick={onRunRace}
              disabled={loading}
              icon="terminal"
              className="h-16 px-6 text-sm"
            >
              Run The Correction Race
            </Button>
          </div>

          {/* Backend Health Check Line */}
          <div className="flex items-center gap-2 font-mono text-xs">
            {healthStatus === 'checking' && (
              <span className="text-bone-500 animate-pulse">Checking backend…</span>
            )}
            {healthStatus === 'ok' && (
              <span className="text-sig-verify flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-sig-verify" />
                Backend healthy at {baseUrl}
              </span>
            )}
            {healthStatus === 'error' && (
              <div className="flex items-center gap-3 text-sig-alarm">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-sig-alarm" />
                  Backend unreachable at {baseUrl}
                </span>
                <button
                  type="button"
                  onClick={checkHealth}
                  className="underline hover:text-bone-50 focus-visible:outline-sig-active"
                >
                  Retry
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 3 Pillar Summary at bottom */}
      <PillarRow />
    </div>
  );
};
