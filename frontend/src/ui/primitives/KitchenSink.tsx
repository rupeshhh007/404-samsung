import React from 'react';
import {
  Button,
  Chip,
  CopyButton,
  Details,
  Eyebrow,
  Hairline,
  Icon,
  Led,
  Odometer,
  Scramble,
  type IconName,
} from './index';

export const KitchenSink: React.FC = () => {
  const allIcons: IconName[] = [
    'mark',
    'lock-closed',
    'lock-open',
    'lock-broken',
    'seal',
    'check',
    'cross',
    'alert',
    'arrow',
    'arrow-right',
    'chevron',
    'chevron-down',
    'copy',
    'terminal',
    'rewind',
    'play',
    'pause',
    'eye',
    'link',
    'stamp',
  ];

  return (
    <div className="min-h-screen bg-ink-950 text-bone-50 p-8 space-y-12 max-w-5xl mx-auto">
      <div>
        <Eyebrow>NIGHT INSTRUMENT · PRIMITIVES GALLERY</Eyebrow>
        <h1 className="text-4xl font-display font-bold uppercase mt-2">Kitchen Sink</h1>
        <Hairline className="mt-4" />
      </div>

      {/* Buttons */}
      <section className="space-y-4">
        <Eyebrow>BUTTONS</Eyebrow>
        <div className="flex flex-wrap items-center gap-4">
          <Button variant="primary">Begin Session</Button>
          <Button variant="primary" icon="arrow-right">With Icon</Button>
          <Button variant="ghost">Run Race</Button>
          <Button variant="ghost" icon="terminal">Terminal</Button>
          <Button variant="danger">Barge In</Button>
          <Button variant="primary" disabled>Disabled Primary</Button>
          <Button variant="ghost" disabled>Disabled Ghost</Button>
          <Button variant="ghost" loading>Loading</Button>
        </div>
      </section>

      {/* Chips */}
      <section className="space-y-4">
        <Eyebrow>CHIPS & SIGNALS</Eyebrow>
        <div className="flex flex-wrap items-center gap-3">
          <Chip variant="active" dot>Active Op</Chip>
          <Chip variant="spec" dot dashed>Anticipate</Chip>
          <Chip variant="pending" dot>Pending</Chip>
          <Chip variant="alarm" icon="alert">Divergence</Chip>
          <Chip variant="adapt" dot>Adapt</Chip>
          <Chip variant="verify" icon="check">Verified</Chip>
          <Chip variant="neutral">Neutral</Chip>
          <Chip variant="slab">Scripted Replay</Chip>
        </div>
      </section>

      {/* LEDs */}
      <section className="space-y-4">
        <Eyebrow>LEDS</Eyebrow>
        <div className="flex items-center gap-6">
          <Led status="active" pulse size={10} aria-label="Active" />
          <Led status="spec" size={10} aria-label="Speculative" />
          <Led status="pending" pulse size={10} aria-label="Pending" />
          <Led status="alarm" pulse size={10} aria-label="Alarm" />
          <Led status="adapt" size={10} aria-label="Adapt" />
          <Led status="verify" size={10} aria-label="Verify" />
          <Led status="neutral" size={10} aria-label="Neutral" />
          <Led status="idle" size={10} aria-label="Idle" />
        </div>
      </section>

      {/* Typography & Odometer & Scramble */}
      <section className="space-y-4">
        <Eyebrow>NUMERICS & SCRAMBLE</Eyebrow>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-end">
          <div>
            <div className="text-xs font-mono text-bone-500 mb-1">ODOMETER</div>
            <div className="text-5xl font-display font-extrabold text-bone-50">
              <Odometer value="11:00" />
            </div>
          </div>
          <div>
            <div className="text-xs font-mono text-bone-500 mb-1">SCRAMBLE</div>
            <div className="text-3xl font-mono text-sig-verify">
              <Scramble text="COMMITTED" duration={0.8} />
            </div>
          </div>
          <div>
            <div className="text-xs font-mono text-bone-500 mb-1">COPY BUTTON</div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-bone-300">01a1084d-58bb</span>
              <CopyButton text="01a1084d-58bb-79a3-8fcb-8d0efbeb5b68" />
            </div>
          </div>
        </div>
      </section>

      {/* Details */}
      <section className="space-y-4">
        <Eyebrow>DETAILS & DEFINITION GRID</Eyebrow>
        <Details
          title="Runtime Metadata"
          defaultOpen
          items={[
            { label: 'Session ID', value: 'sess-01a1084d-58bb-79a3' },
            { label: 'Applied Sequence', value: '#42' },
            { label: 'Fingerprint', value: 'sha256:4a8b79c3d4e5f601a2b3c4d5e6f7a8b9' },
            { label: 'State', value: 'COMMITTED', mono: false },
          ]}
        />
      </section>

      {/* Icons */}
      <section className="space-y-4">
        <Eyebrow>GEOMETRIC ICONS SET</Eyebrow>
        <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-10 gap-4">
          {allIcons.map((name) => (
            <div
              key={name}
              className="flex flex-col items-center gap-2 p-3 border border-ink-600 bg-ink-900"
            >
              <Icon name={name} size={20} className="text-bone-50" />
              <span className="font-mono text-[9px] text-bone-500 truncate max-w-full">
                {name}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};
