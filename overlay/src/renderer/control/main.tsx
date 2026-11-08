import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ControlApp } from "./ControlApp.tsx";
import { ControlProvider } from "./ControlContext.tsx";
import "../skins/fonts.css";
import "./control.css";
import "./sidebar.css";
import "./form.css";
import "./choices.css";
import "./memory.css";
import "./memory-actions.css";
import "./tabs.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Control Center page has no #root element");
}
createRoot(root).render(
  <StrictMode>
    <ControlProvider>
      <ControlApp />
    </ControlProvider>
  </StrictMode>,
);
