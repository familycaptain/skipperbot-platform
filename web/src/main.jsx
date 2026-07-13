import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { installAuthFetch } from "./utils/api";
import { applyTheme, getStoredTheme } from "./utils/theme";

// Attach the bearer token to every same-origin API/ws request (and handle 401 →
// logout). Must run before any component fires a fetch.
installAuthFetch();

// Apply the saved theme on bootstrap (belt-and-suspenders with the inline
// pre-paint script in index.html). Dark is the default. Issue #26.
applyTheme(getStoredTheme());

// NOTE: there is deliberately NO controllerchange auto-reload here anymore.
// It was the cause of the "app refreshes on me 10-15s after I open it" bug: a
// freshly-deployed service worker would claim the open tab on the browser's own
// schedule and this handler blindly reloaded, dumping the user back to the home
// screen mid-use. Updates are now user-driven — the app detects a new version
// INSTANTLY via the WebSocket build_id and shows a blocking "Refresh Now" modal
// (see Shell.jsx); nothing reloads the page unless the user clicks it.

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
