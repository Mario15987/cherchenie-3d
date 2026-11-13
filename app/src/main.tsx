import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/index.css'
import './lib/colors'
import { App } from './App'
import { bootstrap, useDoc } from './store/doc'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
bootstrap()

// Доступ к состоянию из консоли для отладки и e2e-проверок (только dev).
if (import.meta.env.DEV) Object.assign(window, { __recad: useDoc })
