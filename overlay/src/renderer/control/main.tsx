import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ControlApp } from "./ControlApp.tsx";
import { ControlProvider } from "./ControlContext.tsx";
import "./control.css";
import "./form.css";
import "./memory.css";
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
