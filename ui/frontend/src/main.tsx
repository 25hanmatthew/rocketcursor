import React from "react";
import ReactDOM from "react-dom/client";
import * as Sentry from "@sentry/react";
import App from "./App";
import "./styles.css";

// Sentry error monitoring for the frontend — completes the cross-stack story
// (loop + agents + UI backend + browser). Guarded: no-op without VITE_SENTRY_DSN.
const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.VITE_SENTRY_ENV ?? "hackathon",
    sendDefaultPii: true,
    tracesSampleRate: 1.0,
    integrations: [Sentry.browserTracingIntegration()]
  });
  Sentry.setTag("component", "ui-frontend");
  Sentry.setTag("project", "rocketcursor");
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Sentry.ErrorBoundary
      fallback={<div style={{ padding: 24 }}>Something went wrong — the error was reported to Sentry.</div>}
    >
      <App />
    </Sentry.ErrorBoundary>
  </React.StrictMode>
);
