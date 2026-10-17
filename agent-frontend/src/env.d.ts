/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_PREFIX: string
  readonly VITE_DEV_PORT?: string
  readonly VITE_PREVIEW_PORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
