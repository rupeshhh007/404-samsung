import React, { useEffect, useState } from 'react';
import type { ProjectionStore } from '../../state/store';
import { StoryboardClient } from './StoryboardClient';
import { StoryboardControls } from './StoryboardControls';

interface StoryboardOverlayProps {
  readonly store: ProjectionStore;
  readonly onClientReady: (client: StoryboardClient) => void;
}

export const StoryboardOverlay: React.FC<StoryboardOverlayProps> = ({
  store,
  onClientReady,
}) => {
  const [client, setClient] = useState<StoryboardClient | null>(null);

  useEffect(() => {
    const sc = new StoryboardClient(store);
    sc.init(0);
    setClient(sc);
    onClientReady(sc);

    return () => {
      sc.destroy();
    };
  }, [store, onClientReady]);

  if (!client) return null;
  return <StoryboardControls client={client} />;
};

export default StoryboardOverlay;
