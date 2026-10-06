import React, { useState, useEffect } from 'react';
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
    <div className="relative mx-auto flex min-h-[calc(100vh-72px)] w-full max-w-5xl select-none flex-col justify-center px-6 py-14 sm:px-12 lg:px-16">
      <div className="max-w-3xl space-y-8">
        <div>
          <span className="editorial-kicker">Consistency runtime</span>
          <h1
            className={`mt-4 font-voice text-[clamp(64px,10vw,132px)] leading-[0.82] tracking-[-0.055em] text-[var(--console-ink)] transition-opacity duration-300 ${
              fontsReady ? 'opacity-100' : 'opacity-80'
            }`}
          >
            Reality,<br />without guesswork.
          </h1>
        </div>

        {/* One-Line Mission Statement */}
        <p className="max-w-xl font-sans text-[clamp(17px,2vw,22px)] leading-relaxed text-[var(--console-muted)]">
          Anticipate early. Commit safely. Speak only what reality confirms.
        </p>

        {/* Primary CTA & Health Check */}
        <div className="pt-2 flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <Button
            variant="primary"
            onClick={handleBegin}
            loading={loading}
            iconRight="arrow-right"
            className="h-12 border-0 bg-[var(--console-ink)] px-6 text-sm font-bold text-[var(--console-paper)] shadow-none"
          >
            Begin Session
          </Button>

          {/* Backend Status Line */}
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[var(--console-muted)]">
            {healthStatus === 'checking' && (
              <span className="animate-pulse">Checking backend…</span>
            )}
            {healthStatus === 'ok' && (
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--console-ink)]" />
                Backend healthy
              </span>
            )}
            {healthStatus === 'error' && (
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--console-muted)]" />
                Backend unreachable at {baseUrl}
                <button
                  type="button"
                  onClick={checkHealth}
                  className="ml-1 underline"
                >
                  Retry
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
};
