import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AdminApp from './App'
import '../../m3a-admin/tokens.css'
import './styles.css'
createRoot(document.getElementById('root')!).render(<StrictMode><AdminApp/></StrictMode>)
