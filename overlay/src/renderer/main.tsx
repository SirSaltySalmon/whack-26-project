import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import "./styles.css";
import "./cards.css";
import "./companion.css";
import "./debug.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Overlay page has no #root element");
}
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
