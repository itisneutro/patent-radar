// Шрифты из npm-пакетов @fontsource (вариативные): работают офлайн, внешних запросов нет.
// В файлах есть латиница и кириллица; браузер скачивает только нужные наборы символов.
import '@fontsource-variable/unbounded'
import '@fontsource-variable/manrope'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
