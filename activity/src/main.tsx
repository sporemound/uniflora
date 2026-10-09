import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/space-grotesk/wght.css";
import "@fontsource-variable/source-sans-3/wght.css";
import "@fontsource-variable/source-sans-3/wght-italic.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-700.css";
import App from "./App";
import { DisclaimerSplash } from "./components/DisclaimerSplash";
import "./styles.css";

const DISCLAIMER_AGREED_KEY = "missing-interior:disclaimer-agreed:v2";

function SiteEntry() {
  const [showDisclaimer, setShowDisclaimer] = useState(() => {
    try {
      return window.sessionStorage.getItem(DISCLAIMER_AGREED_KEY) !== "yes";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    if (!showDisclaimer) return;
    const previousOverflow = document.body.style.overflow;
    const previousHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
      document.documentElement.style.overflow = previousHtmlOverflow;
    };
  }, [showDisclaimer]);

  return <>
    <div inert={showDisclaimer} aria-hidden={showDisclaimer}>
      <App onShowDisclaimer={() => setShowDisclaimer(true)} />
    </div>
    {showDisclaimer ? <DisclaimerSplash onContinue={() => {
      try {
        window.sessionStorage.setItem(DISCLAIMER_AGREED_KEY, "yes");
      } catch {
        // The agreement still works when browser storage is unavailable.
      }
      setShowDisclaimer(false);
    }} /> : null}
  </>;
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing #root element.");
}

createRoot(root).render(
  <StrictMode>
    <SiteEntry />
  </StrictMode>,
);
