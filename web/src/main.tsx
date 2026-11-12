import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { restoreSession } from "./app/session";
import "./styles.css";

const container = document.getElementById("root");

if (container !== null) {
  // A reload keeps the session: the HttpOnly cookie is checked once here.
  void restoreSession();
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
