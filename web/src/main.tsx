import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'

import { clearRetiredReadingCache } from './retiredReadingCache'

// Initialize before mounting so an offline cold start can resume on reconnect.
onlineManager.setOnline(navigator.onLine)

const queryClient = new QueryClient()
void clearRetiredReadingCache()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
