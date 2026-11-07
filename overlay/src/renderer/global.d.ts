import type { OverlayBridge } from "../lib/bridge.ts";

declare global {
  interface Window {
    overlay: OverlayBridge;
  }
}
