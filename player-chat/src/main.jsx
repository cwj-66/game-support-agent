import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { ConfigProvider } from 'antd'
import './theme.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ConfigProvider theme={{ token: { colorPrimary: '#247667', colorText: '#22332e', colorBorder: '#e3e8e1', borderRadius: 10, fontFamily: 'Inter, Segoe UI, Microsoft YaHei, sans-serif' } }}><App /></ConfigProvider>
  </StrictMode>,
)
