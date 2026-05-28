import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// Auto-reload when a new service worker takes over (prevents stale chunk errors).
// Skip if we just did an intentional update-reload (Shell "Update Available" button)
// to avoid a double-reload that bounces the user back to the home screen.
// The flag is set before reload and checked here with NO time limit — precaching
// can take an unpredictable amount of time before controllerchange fires.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (sessionStorage.getItem("sw-update-reload")) {
      sessionStorage.removeItem("sw-update-reload");
      return; // intentional reload already handled it
    }
    window.location.reload();
  });
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
