import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import Dashboard from './v2/Dashboard.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import './index.css';

// v2 dashboard by default; the previous console stays available at ?classic=1
const classic = new URLSearchParams(window.location.search).get('classic') === '1';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      {classic ? <App /> : <Dashboard />}
    </ErrorBoundary>
  </React.StrictMode>
);
