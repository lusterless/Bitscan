import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";

const container = document.getElementById("root");

if (container !== null) {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
