import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './SoundAgentPanel.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>
)
