import React, { createContext, useContext, useState, useCallback, useRef } from 'react';

interface LiveAnnouncement {
  readonly id: string;
  readonly message: string;
}

interface LiveRegionsContextValue {
  readonly announcePolite: (message: string) => void;
  readonly announceAssertive: (message: string) => void;
}

const LiveRegionsContext = createContext<LiveRegionsContextValue>({
  announcePolite: () => {},
  announceAssertive: () => {},
});

export const useLiveAnnouncement = () => useContext(LiveRegionsContext);

export const LiveRegionsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [politeList, setPoliteList] = useState<readonly LiveAnnouncement[]>([]);
  const [assertiveList, setAssertiveList] = useState<readonly LiveAnnouncement[]>([]);

  const lastPoliteRef = useRef<string>('');
  const lastAssertiveRef = useRef<string>('');

  const announcePolite = useCallback((message: string) => {
    if (!message || message === lastPoliteRef.current) return;
    lastPoliteRef.current = message;
    const id = `polite-${Date.now()}-${Math.random()}`;
    setPoliteList((prev) => [...prev, { id, message }]);

    setTimeout(() => {
      setPoliteList((prev) => prev.filter((item) => item.id !== id));
      if (lastPoliteRef.current === message) {
        lastPoliteRef.current = '';
      }
    }, 4000);
  }, []);

  const announceAssertive = useCallback((message: string) => {
    if (!message || message === lastAssertiveRef.current) return;
    lastAssertiveRef.current = message;
    const id = `assertive-${Date.now()}-${Math.random()}`;
    setAssertiveList((prev) => [...prev, { id, message }]);

    setTimeout(() => {
      setAssertiveList((prev) => prev.filter((item) => item.id !== id));
      if (lastAssertiveRef.current === message) {
        lastAssertiveRef.current = '';
      }
    }, 4000);
  }, []);

  return (
    <LiveRegionsContext.Provider value={{ announcePolite, announceAssertive }}>
      {children}

      {/* Screen reader polite live region */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {politeList.map((item) => (
          <p key={item.id}>{item.message}</p>
        ))}
      </div>

      {/* Screen reader assertive live region */}
      <div
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className="sr-only"
      >
        {assertiveList.map((item) => (
          <p key={item.id}>{item.message}</p>
        ))}
      </div>
    </LiveRegionsContext.Provider>
  );
};
