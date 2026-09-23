import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';

const rootElement = document.getElementById('root');

if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} else {
  // In environments without index.html or before HTML mounting,
  // report an informative diagnostic without throwing unhandled exceptions.
  console.warn(
    '[INTERLOCK UI-001] Target DOM element with ID "root" was not found in document. ' +
    'Standard browser hosts require frontend/index.html to mount this entrypoint.'
  );
}
