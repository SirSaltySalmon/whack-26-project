import { useEffect, useRef, useState } from "react";
import type { Brain } from "../../lib/protocol.generated.ts";
import { BrainSocket, PROTOCOL_VERSION } from "../lib/brainSocket.ts";

export interface BrainLink {
  socket: BrainSocket | null;
  /** Counts connections. Zero means never connected. */
  generation: number;
}

export function useBrainLink(onMessage: (message: Brain) => void): BrainLink {
  const handler = useRef(onMessage);
  useEffect(() => {
    handler.current = onMessage;
  });

  const [link, setLink] = useState<BrainLink>({ socket: null, generation: 0 });

  useEffect(() => {
    const sendReady = (socket: BrainSocket): void => {
      socket.send({
        type: "overlay.ready",
        protocol_version: PROTOCOL_VERSION,
        display_scale: window.devicePixelRatio,
        width: window.innerWidth,
        height: window.innerHeight,
      });
    };

    const socket: BrainSocket = new BrainSocket({
      onOpen: () => {
        sendReady(socket);
        setLink((current) => ({ socket, generation: current.generation + 1 }));
      },
      onMessage: (message) => handler.current(message),
    });
    setLink({ socket, generation: 0 });

    // Masks depend on the scale, so the brain has to hear if Windows scaling changes mid-run.
    let scale = window.devicePixelRatio;
    const onResize = (): void => {
      if (window.devicePixelRatio !== scale) {
        scale = window.devicePixelRatio;
        sendReady(socket);
      }
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      socket.close();
    };
  }, []);

  return link;
}
