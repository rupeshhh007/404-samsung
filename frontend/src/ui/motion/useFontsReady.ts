import { useState, useEffect } from 'react';

/**
 * Font gate hook: waits for Bricolage Grotesque, Instrument Serif, and JetBrains Mono
 * to be ready in the document before SplitText or animations measure DOM metrics.
 * Times out after 1500ms to prevent blocking.
 */
export function useFontsReady(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (typeof document === 'undefined' || !document.fonts) {
      setReady(true);
      return;
    }

    let active = true;
    const fontPromises = [
      document.fonts.load('800 16px "Bricolage Grotesque Variable"'),
      document.fonts.load('italic 16px "Instrument Serif"'),
      document.fonts.load('400 16px "JetBrains Mono Variable"'),
      document.fonts.ready,
    ];

    const timeout = new Promise<void>((resolve) => {
      setTimeout(resolve, 1500);
    });

    Promise.race([
      Promise.all(fontPromises),
      timeout,
    ]).then(() => {
      if (active) {
        setReady(true);
      }
    });

    return () => {
      active = false;
    };
  }, []);

  return ready;
}
