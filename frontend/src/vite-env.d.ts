/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LOOPBACK?: string
  readonly VITE_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module "*.wav" {
  const src: string
  export default src
}
