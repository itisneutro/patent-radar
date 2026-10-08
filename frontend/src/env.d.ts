/** Переменные окружения интерфейса: файл .env.api и другие .env-файлы Vite. */
interface ImportMetaEnv {
  /** Источник данных: "api" — бэкенд через /api/search; не задано или другое значение — мок. */
  readonly VITE_API_MODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
