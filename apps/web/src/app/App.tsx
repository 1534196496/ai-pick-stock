import { BrowserRouter } from 'react-router-dom';

import { AppRoutes } from './routes';

/** 提供浏览器历史并挂载应用级路由。 */
export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
