import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

const container = document.getElementById("root");

if (container !== null) {
  createRoot(container).render(
    <StrictMode>
      <p>Bitscan</p>
    </StrictMode>,
  );
}
