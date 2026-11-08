import { useEffect, useRef, useState } from "react";
import type { Brain } from "../../lib/protocol.generated.ts";
import { BrainSocket, PROTOCOL_VERSION } from "../lib/brainSocket.ts";

export interface BrainLink {
  socket: BrainSocket | null;
  /** Counts connections. Zero means never connected. */
  generation: number;
  /** False while the brain is away, so controls that need it can say so. */
  connected: boolean;
}

export function useBrainLink(onMessage: (message: Brain) => void): BrainLink {
  const handler = useRef(onMessage);
  useEffect(() => {
    handler.current = onMessage;
  });

  const [link, setLink] = useState<BrainLink>({
    socket: null,
    generation: 0,
    connected: false,
  });

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
        setLink((current) => ({
          socket,
          generation: current.generation + 1,
          connected: true,
        }));
      },
      onMessage: (message) => handler.current(message),
      // Only this socket's own link: a socket closed on unmount mustn't mark a newer one offline.
      onClose: () =>
        setLink((current) =>
          current.socket === socket
            ? { ...current, connected: false }
            : current,
        ),
    });
    setLink({ socket, generation: 0, connected: false });

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
