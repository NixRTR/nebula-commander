/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** App version baked in at build time (docker/frontend/Dockerfile), from the
   * release tag. Unset ("") for local dev builds. */
  readonly VITE_APP_VERSION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
