import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import './styles/global.css';

const container = document.getElementById('root');

if (container === null) {
  throw new Error('缺少应用根节点 #root');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
