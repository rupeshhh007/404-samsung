import React, { useState, useEffect } from 'react';
import { LockSnapMark } from './LockSnapMark';
import { PillarRow } from './PillarRow';
import { Button } from '../primitives/Button';
import { useFontsReady } from '../motion/useFontsReady';

interface IdleScreenProps {
  readonly onBeginSession: () => Promise<boolean>;
  readonly onHealthCheck: () => Promise<boolean>;
  readonly baseUrl: string;
}

export const IdleScreen: React.FC<IdleScreenProps> = ({
  onBeginSession,
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
    <div className="relative min-h-[calc(100vh-64px)] flex flex-col justify-between p-6 sm:p-10 lg:p-14 max-w-5xl mx-auto w-full z-10 select-none">
      {/* Center Hero */}
      <div className="flex flex-col justify-center my-auto space-y-6 max-w-3xl">
        <div className="flex items-center gap-4">
          <LockSnapMark size={72} />
          <div>
            <h1
              className={`font-display font-extrabold uppercase tracking-tight text-bone-50 leading-none text-[clamp(48px,6vw,84px)] transition-opacity duration-300 ${
                fontsReady ? 'opacity-100' : 'opacity-80'
              }`}
            >
              INTERLOCK
            </h1>
            <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-bone-500">
              CONSISTENCY RUNTIME
            </span>
          </div>
        </div>

        {/* One-Line Mission Statement */}
        <p className="font-voice italic text-[clamp(22px,2.2vw,32px)] text-bone-100 leading-snug">
          Anticipate early. Commit safely. Speak only what reality confirms.
        </p>

        {/* Primary CTA & Health Check */}
        <div className="pt-2 flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <Button
            variant="primary"
            onClick={handleBegin}
            loading={loading}
            iconRight="arrow-right"
            className="h-12 px-6 text-sm font-bold"
          >
            Begin Session
          </Button>

          {/* Backend Status Line */}
          <div className="flex items-center gap-2 font-mono text-xs text-bone-500">
            {healthStatus === 'checking' && (
              <span className="animate-pulse">Checking backend…</span>
            )}
            {healthStatus === 'ok' && (
              <span className="text-sig-verify flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-sig-verify" />
                Backend healthy
              </span>
            )}
            {healthStatus === 'error' && (
              <div className="flex items-center gap-2 text-sig-alarm">
                <span className="w-2 h-2 rounded-full bg-sig-alarm" />
                Backend unreachable at {baseUrl}
                <button
                  type="button"
                  onClick={checkHealth}
                  className="underline hover:text-bone-50 ml-1"
                >
                  Retry
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Honest 3-Pillar Row */}
      <PillarRow />
    </div>
  );
};
