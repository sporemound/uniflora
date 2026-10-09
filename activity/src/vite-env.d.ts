/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DISCORD_CLIENT_ID?: string;
  readonly VITE_ENABLE_DISCORD_SDK?: string;
  readonly VITE_MAP_TILE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
