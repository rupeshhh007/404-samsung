import type { ProjectionStore } from '../../state/store';
import type { ProjectionEventMessage, SessionProjection } from '../../api/types';
import type { UserPromptEntry } from '../../ui/viewmodel/transcript';
import realP0 from './fixtures/real-p0.json';
import scriptedContinuation from './fixtures/scripted-continuation.json';

const INITIAL_PROJECTION: SessionProjection = {
  intent: null,
  operations: [],
  effects: [],
  evidence: [],
  claims: [],
  divergences: [],
  plans: [],
  speech: [],
  metrics: {
    session_id: realP0.session_id,
    through_sequence: 0,
    counters: {},
    durations_ms: {},
    gauges: {},
  },
};

export class StoryboardClient {
  private readonly store: ProjectionStore;
  private readonly events: readonly ProjectionEventMessage[];
  public readonly sessionId: string;
  private currentSequence: number = 0;
  private isPlaying: boolean = false;
  private playbackSpeed: number = 1;
  private timerId: ReturnType<typeof setTimeout> | null = null;
  private listeners: Set<() => void> = new Set();

  constructor(store: ProjectionStore) {
    this.store = store;
    this.sessionId = realP0.session_id;
    this.events = [
      ...realP0.events,
      ...scriptedContinuation.events,
    ] as unknown as ProjectionEventMessage[];
  }

  public init(startSequence = 0): void {
    this.jumpTo(startSequence);
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  public getSequence(): number {
    return this.currentSequence;
  }

  public getTotalSequences(): number {
    return this.events.length;
  }

  public getIsPlaying(): boolean {
    return this.isPlaying;
  }

  public getPlaybackSpeed(): number {
    return this.playbackSpeed;
  }

  public getIsScriptedContinuation(): boolean {
    return this.currentSequence >= 32;
  }

  public getUserPrompts(): readonly UserPromptEntry[] {
    const prompts: UserPromptEntry[] = [];
    if (this.currentSequence >= 1) {
      prompts.push({
        id: 'prompt-1',
        text: 'Book 11:00.',
        acceptedSequence: 1,
      });
    }
    if (this.currentSequence >= 8) {
      prompts.push({
        id: 'prompt-2',
        text: 'Actually, make it 12:00.',
        acceptedSequence: 8,
      });
    }
    return prompts;
  }

  public jumpTo(targetSeq: number): void {
    const clamped = Math.max(0, Math.min(this.events.length, targetSeq));
    this.store.reset();
    this.store.markConnected();

    this.store.applySnapshot({
      type: 'snapshot',
      schema_version: 1,
      session_id: this.sessionId,
      through_sequence: 0,
      projection: INITIAL_PROJECTION,
    });

    for (let i = 0; i < clamped; i++) {
      const ev = this.events[i];
      if (ev) {
        this.store.applyEvent(ev);
      }
    }

    this.currentSequence = clamped;
    this.notify();
  }

  public stepForward(): boolean {
    if (this.currentSequence >= this.events.length) {
      this.pause();
      return false;
    }

    const nextEvent = this.events[this.currentSequence];
    if (nextEvent) {
      this.store.applyEvent(nextEvent);
      this.currentSequence += 1;
      this.notify();
      return true;
    }
    return false;
  }

  public stepBackward(): boolean {
    if (this.currentSequence <= 0) return false;
    this.jumpTo(this.currentSequence - 1);
    return true;
  }

  public play(): void {
    if (this.isPlaying) return;
    if (this.currentSequence >= this.events.length) {
      this.jumpTo(0);
    }
    this.isPlaying = true;
    this.notify();
    this.scheduleNextStep();
  }

  public pause(): void {
    if (!this.isPlaying) return;
    this.isPlaying = false;
    if (this.timerId !== null) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
    this.notify();
  }

  public togglePlay(): void {
    if (this.isPlaying) {
      this.pause();
    } else {
      this.play();
    }
  }

  public setSpeed(speed: number): void {
    this.playbackSpeed = speed;
    this.notify();
    if (this.isPlaying) {
      if (this.timerId !== null) {
        clearTimeout(this.timerId);
      }
      this.scheduleNextStep();
    }
  }

  private scheduleNextStep(): void {
    if (!this.isPlaying) return;

    // Delay varies slightly per step to give realistic pace, scaled by speed
    // Base delay ~400ms per event
    const baseDelayMs = 450;
    const delay = Math.max(50, Math.round(baseDelayMs / this.playbackSpeed));

    this.timerId = setTimeout(() => {
      const advanced = this.stepForward();
      if (advanced && this.isPlaying) {
        this.scheduleNextStep();
      } else {
        this.pause();
      }
    }, delay);
  }

  public getAllEvents(): readonly ProjectionEventMessage[] {
    return this.events.slice(0, this.currentSequence);
  }

  public destroy(): void {
    this.pause();
    this.listeners.clear();
  }
}
