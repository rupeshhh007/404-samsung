import React from 'react';
import ReactDOM from 'react-dom/client';

// Typography (Self-hosted via Fontsource)
import '@fontsource-variable/bricolage-grotesque/wdth.css';
import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';
import '@fontsource-variable/jetbrains-mono/wght.css';

// Design Tokens & Styles
import './styles/tokens.css';
import './styles/grain.css';
import './styles/index.css';

// Motion & GSAP Initialization
import './ui/motion/gsap';

import App from './App';

const rootElement = document.getElementById('root');

if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} else {
  console.warn(
    '[INTERLOCK UI-001] Target DOM element with ID "root" was not found in document.'
  );
}
