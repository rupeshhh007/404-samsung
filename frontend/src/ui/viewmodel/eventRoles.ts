import type { IconName } from '../primitives/Icon';

export type EventLane = 'SYSTEM' | 'INTENT' | 'EXECUTION' | 'REALITY' | 'VOICE';
export type EventRole =
  | 'neutral'
  | 'active'
  | 'spec'
  | 'pending'
  | 'alarm'
  | 'adapt'
  | 'verify';

export interface EventRoleInfo {
  readonly lane: EventLane;
  readonly role: EventRole;
  readonly label: string;
  readonly icon?: IconName;
  readonly dashed?: boolean;
}

const EVENT_ROLE_TABLE: Record<string, EventRoleInfo> = {
  SessionStarted: { lane: 'SYSTEM', role: 'neutral', label: 'Session initialized' },
  UserInputObserved: { lane: 'INTENT', role: 'neutral', label: 'You spoke / typed' },
  InputAccepted: { lane: 'INTENT', role: 'neutral', label: 'User input accepted' },
  TranscriptHypothesisObserved: { lane: 'INTENT', role: 'spec', label: 'Transcript hypothesis' },
  ControlIntentInterpreted: { lane: 'INTENT', role: 'neutral', label: 'Control interpreted' },
  IntentRevisionProposed: { lane: 'INTENT', role: 'spec', label: 'Intent proposed' },
  IntentRevisionCommitted: { lane: 'INTENT', role: 'active', label: 'Intent committed' },
  IntentAuthorizationChanged: { lane: 'INTENT', role: 'pending', label: 'Authorization changed' },

  // ANTICIPATE branch events
  BranchPredicted: { lane: 'EXECUTION', role: 'spec', label: 'Branch predicted', dashed: true },
  BranchPreparationStarted: { lane: 'EXECUTION', role: 'spec', label: 'Branch preparing', dashed: true },
  BranchPreparationCompleted: { lane: 'EXECUTION', role: 'spec', label: 'Branch prepared', dashed: true },
  BranchPromoted: { lane: 'EXECUTION', role: 'spec', label: 'Branch promoted', dashed: true },
  BranchInvalidated: { lane: 'EXECUTION', role: 'spec', label: 'Branch invalidated', dashed: true },

  // Execution operations
  OperationCreated: { lane: 'EXECUTION', role: 'active', label: 'Operation created' },
  OperationPreparationStarted: { lane: 'EXECUTION', role: 'active', label: 'Operation preparing' },
  OperationPrepared: { lane: 'EXECUTION', role: 'active', label: 'Operation ready' },
  ToolDispatchRequested: { lane: 'EXECUTION', role: 'active', label: 'Dispatch requested' },
  ToolDispatchAccepted: { lane: 'EXECUTION', role: 'active', label: 'Dispatch accepted' },
  SafePointReached: { lane: 'EXECUTION', role: 'active', label: 'Safe point reached' },

  // Cancellations
  CancellationRequested: { lane: 'EXECUTION', role: 'pending', label: 'Cancellation requested' },
  CancellationAcknowledged: { lane: 'EXECUTION', role: 'pending', label: 'Cancellation acknowledged' },
  CancellationRejected: { lane: 'EXECUTION', role: 'pending', label: 'Cancellation rejected', dashed: true },
  CancellationTooLate: { lane: 'EXECUTION', role: 'pending', label: 'Cancellation too late', icon: 'stamp' },

  // Tool outcomes
  ToolResultObserved: { lane: 'EXECUTION', role: 'active', label: 'Tool result observed' },
  ToolTimedOut: { lane: 'EXECUTION', role: 'pending', label: 'Tool timed out' },

  // Reality
  WorldEffectObserved: { lane: 'REALITY', role: 'verify', label: 'World effect observed' },
  EvidenceRecorded: { lane: 'REALITY', role: 'neutral', label: 'Evidence recorded' },

  // Voice & Claims
  ClaimProposed: { lane: 'VOICE', role: 'pending', label: 'Claim proposed' },
  ClaimStateChanged: { lane: 'VOICE', role: 'pending', label: 'Claim state changed' },
  SpeechActProposed: { lane: 'VOICE', role: 'neutral', label: 'Speech proposed' },
  SpeechActApproved: { lane: 'VOICE', role: 'verify', label: 'TRUTHLOCK approved', icon: 'seal' },
  SpeechActBlocked: { lane: 'VOICE', role: 'alarm', label: 'TRUTHLOCK blocked', icon: 'alert' },
  SpeechQueued: { lane: 'VOICE', role: 'neutral', label: 'Speech queued' },
  SpeechEmissionStarted: { lane: 'VOICE', role: 'neutral', label: 'Speech started' },
  SpeechEmissionFinished: { lane: 'VOICE', role: 'neutral', label: 'Speech finished' },
  SpeechEmissionCompleted: { lane: 'VOICE', role: 'neutral', label: 'Speech completed' },
  SpeechEmissionFailed: { lane: 'VOICE', role: 'alarm', label: 'Speech failed', icon: 'alert' },
  SpeechCancellationRequested: { lane: 'VOICE', role: 'pending', label: 'Speech cancel requested' },
  SpeechCancelled: { lane: 'VOICE', role: 'pending', label: 'Speech cancelled' },

  // Divergence & Reconciliation
  DivergenceDetected: { lane: 'REALITY', role: 'alarm', label: 'Divergence detected', icon: 'alert' },
  ReconciliationPlanned: { lane: 'EXECUTION', role: 'adapt', label: 'Repair planned' },
  ReconciliationAuthorized: { lane: 'EXECUTION', role: 'adapt', label: 'Repair authorized' },
  ReconciliationStepChanged: { lane: 'EXECUTION', role: 'adapt', label: 'Repair step changed' },
  ReconciliationDenied: { lane: 'EXECUTION', role: 'alarm', label: 'Repair denied' },
  DivergenceResolved: { lane: 'REALITY', role: 'verify', label: 'Divergence resolved', icon: 'check' },

  // Faults & protocol violations
  DemoFaultConfigured: { lane: 'SYSTEM', role: 'pending', label: 'Fault injected (SCRIPTED)' },
  FaultActivated: { lane: 'SYSTEM', role: 'pending', label: 'Fault injected (SCRIPTED)' },
  ProtocolViolationObserved: { lane: 'SYSTEM', role: 'alarm', label: 'Protocol violation', icon: 'alert' },
};

function humanizeCamelCase(str: string): string {
  return str.replace(/([A-Z])/g, ' $1').trim();
}

/**
 * Returns lane, role, label, and icon for any event type.
 * Unknown events return a safe neutral fallback on the SYSTEM lane.
 */
export function getEventRoleInfo(eventType: string): EventRoleInfo {
  const match = EVENT_ROLE_TABLE[eventType];
  if (match) return match;

  return {
    lane: 'SYSTEM',
    role: 'neutral',
    label: humanizeCamelCase(eventType),
  };
}
