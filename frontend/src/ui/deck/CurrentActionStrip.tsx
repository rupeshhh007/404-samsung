import React from 'react';
import type { SessionProjection } from '../../api/types';
import { selectActiveOperation, selectActiveDivergence } from '../viewmodel/slots';

interface CurrentActionStripProps {
  readonly projection: SessionProjection | null;
}

export const CurrentActionStrip: React.FC<CurrentActionStripProps> = ({ projection }) => {
  const activeOp = selectActiveOperation(projection);

  let text = 'System ready';
  if (activeOp) {
    if (activeOp.cancellation_state === 'TOO_LATE') {
      text = 'Cancellation was too late';
    } else if (activeOp.cancellation_state === 'REQUESTED') {
      text = 'Cancellation requested';
    } else if (activeOp.state === 'CANCELLED') {
      text = 'Cancelled at safepoint';
    } else if (
      activeOp.state === 'DISPATCHED' ||
      activeOp.state === 'WAITING' ||
      activeOp.state === 'PREPARING' ||
      activeOp.state === 'READY'
    ) {
      text = 'Booking appointment · Executing';
    } else if (activeOp.state === 'SUCCEEDED') {
      text = 'Booking appointment · Completed';
    } else if (activeOp.state === 'TIMED_OUT') {
      text = 'Booking appointment · Outcome unknown';
    } else if (activeOp.state === 'FAILED') {
      text = 'Booking appointment · Failed';
    }
  }
  const divergence = selectActiveDivergence(projection);
  if (divergence?.state === 'OPEN' || divergence?.state === 'ESCALATED') {
    text = 'Divergence open · no repair started';
  }

  return (
    <div className="editorial-action select-none">
      <span className="editorial-action-label">Current action</span>
      <span className="editorial-action-value">
        {text}
      </span>
    </div>
  );
};
