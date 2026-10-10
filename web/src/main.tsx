import { onlineManager } from '@tanstack/react-query'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'

import {
  createDigestPersister,
  createQueryClient,
  digestPersistenceOptions,
} from './queryPersistence'

// Initialize before mounting so an offline cold start can resume on reconnect.
onlineManager.setOnline(navigator.onLine)

const queryClient = createQueryClient()
const persister = createDigestPersister()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{ ...digestPersistenceOptions, persister }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </PersistQueryClientProvider>
  </StrictMode>,
)
