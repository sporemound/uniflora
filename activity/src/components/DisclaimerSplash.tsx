import { useEffect, useRef, useState, type FormEvent } from "react";

interface DisclaimerSplashProps {
  onContinue: () => void;
}

export function DisclaimerSplash({ onContinue }: DisclaimerSplashProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [agreed, setAgreed] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    dialog?.focus();
    if (dialog) dialog.scrollTop = 0;
    return () => { if (dialog?.open) dialog.close(); };
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (agreed) onContinue();
  }

  return (
    <dialog
      ref={dialogRef}
      className="disclaimer-splash"
      tabIndex={-1}
      aria-modal="true"
      aria-labelledby="disclaimer-heading"
      onCancel={(event) => event.preventDefault()}
    >
      <div className="disclaimer-splash__grid" aria-hidden="true" />
      <div className="disclaimer-splash__shell">
        <header className="disclaimer-splash__masthead">
          <span className="disclaimer-splash__mark" aria-hidden="true">MI<span>·</span>01</span>
          <span>Distributed Analysis Console</span>
          <span>Public access notice</span>
        </header>

        <div className="disclaimer-splash__layout">
          <div className="disclaimer-splash__intro">
            <p className="disclaimer-splash__kicker">Before you enter the record</p>
            <h1 id="disclaimer-heading">Disclaimer <span>&amp;</span><br />Important Information</h1>
            <p className="disclaimer-splash__subtitle">The Missing Interior</p>
            <div className="disclaimer-splash__signal" aria-hidden="true">
              <span className="disclaimer-splash__signal-orbit" />
              <span className="disclaimer-splash__signal-core" />
              <span className="disclaimer-splash__signal-axis disclaimer-splash__signal-axis--one" />
              <span className="disclaimer-splash__signal-axis disclaimer-splash__signal-axis--two" />
              <span className="disclaimer-splash__signal-label">Observation / 00</span>
            </div>
            <p className="disclaimer-splash__aside">A fictional investigation with a real public record.</p>
          </div>

          <div className="disclaimer-splash__content">
            <section aria-labelledby="disclaimer-project">
              <span className="disclaimer-splash__index">01 / Project notice</span>
              <h2 id="disclaimer-project">AI-Assisted Project Notice</h2>
              <p>
                Welcome to my AI-assisted game, released as a publicly observable website.
                This project is based on a fictional anomalous observation recorded by various
                agencies through scientific observation platforms placed around the contiguous
                United States. Through collaborative progression, players influence potential
                stage outcomes, with learning tools designed to provide insight into actual
                scientific professions.
              </p>
            </section>

            <section aria-labelledby="disclaimer-email">
              <span className="disclaimer-splash__index">02 / Access &amp; privacy</span>
              <h2 id="disclaimer-email">Email Privacy Recommendation</h2>
              <p>
                Participation in the live game state currently requires an email address to join.
                If you&apos;re uncomfortable using your personal email, you can use a private alias
                address. Services such as Proton Mail offer free aliases. Choose an address you
                can keep receiving mail at: a temporary inbox may prevent you from returning to
                your existing player account and ledger.
              </p>
              <p>
                To request a sign-in link, enter an address you can access and complete the
                Cloudflare bot check. We use Resend to email a link that expires after 15 minutes.
                Opening the link shows a confirmation page; you sign in only after selecting
                Continue, and each link works once. Requests are rate limited, and your session
                uses a Secure, HttpOnly cookie. Only open links you requested on this site, never
                share or forward them, and ignore unexpected sign-in emails.
              </p>
            </section>

            <section aria-labelledby="disclaimer-data">
              <span className="disclaimer-splash__index">03 / Public record &amp; AI</span>
              <h2 id="disclaimer-data">Data &amp; AI Training Disclosure</h2>
              <p>
                This platform has a public, permanent game ledger. Messages you post to the shared
                Hypha chat can be read by anyone with the website link, including after you leave.
                Chat questions are sent to Google Gemini to generate replies. Google&apos;s use of
                Gemini API content for product improvement, including model training, depends on
                the project&apos;s API billing tier: unpaid-tier content may be used for that purpose;
                Google says paid-tier prompts and responses are not. The public record and sending
                a submitted chat question to Gemini are part of participating in those features.
                Do not submit personal, sensitive, or confidential information.
              </p>
            </section>

            <form className="disclaimer-splash__entry" onSubmit={submit}>
              <label className="disclaimer-splash__agreement">
                <input
                  type="checkbox"
                  checked={agreed}
                  onChange={(event) => setAgreed(event.target.checked)}
                  required
                />
                <span>I have read and agree to the public record and AI processing described above.</span>
              </label>
              <button type="submit" disabled={!agreed}>
                Enter the console <span aria-hidden="true">↗</span>
              </button>
            </form>
          </div>
        </div>

        <footer className="disclaimer-splash__footer">
          <span>Fictional case / Public observation</span>
          <span>Read before participating</span>
        </footer>
      </div>
    </dialog>
  );
}
