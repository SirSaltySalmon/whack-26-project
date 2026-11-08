import type { OverlayBridge } from "../lib/bridge.ts";
import type { ControlBridge } from "../lib/controlBridge.ts";

declare global {
  interface Window {
    /** Only in the overlay window. */
    overlay: OverlayBridge;
    /** Only in the Control Center window. */
    control: ControlBridge;
  }
}
