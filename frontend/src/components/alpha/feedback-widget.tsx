"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/panel";
import {
  buildReport,
  FEEDBACK_KINDS,
  FEEDBACK_LABEL,
  formatReport,
  submitFeedback,
  type FeedbackKind,
  type FeedbackOutcome,
} from "@/lib/feedback";
import { cn } from "@/lib/utils";

/**
 * FLOATING FEEDBACK
 *
 * Present on every page of the instrument, because the moment a tester notices
 * something is the only moment they will report it. A feedback link that lives
 * on one page collects feedback about that page.
 *
 * Where the report goes is `lib/feedback.ts`'s problem, not this component's.
 * When nothing is configured the report is shown back as copyable text rather
 * than swallowed — during an alpha the likeliest destination is a person, and
 * losing what a tester wrote is the fastest way to stop them writing again.
 */
export function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<FeedbackKind>("bug");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<FeedbackOutcome | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    // Focus returns to the control that opened the panel; leaving it on a
    // removed node strands keyboard users at the top of the document.
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    textareaRef.current?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    function onPointer(event: MouseEvent) {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open, close]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (message.trim() === "" || busy) return;

    setBusy(true);
    const result = await submitFeedback(buildReport(kind, message));
    setBusy(false);
    setOutcome(result);

    if (result.status === "redirected") {
      window.open(result.url, "_blank", "noopener,noreferrer");
      setMessage("");
    }
    if (result.status === "sent") {
      setMessage("");
    }
  }

  function reset() {
    setOutcome(null);
    setMessage("");
    setKind("bug");
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn(
          // Sits above the mobile nav bar so it never covers navigation.
          "fixed bottom-20 right-4 z-50 flex items-center gap-2 rounded-chip border border-line bg-elevated/95 px-3 py-2 text-xs text-ink-dim shadow-lg backdrop-blur-xl transition-colors lg:bottom-6 lg:right-6",
          "hover:border-line-bright hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma",
        )}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          className="size-4"
          aria-hidden
        >
          <path
            d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.9 8.9 0 0 1-3.8-.8L3 21l1.9-5a8.4 8.4 0 0 1 3.7-11.3 8.4 8.4 0 0 1 12.4 6.8Z"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Feedback
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="false"
          aria-label="Send feedback"
          className="fixed bottom-32 right-4 z-50 w-[min(22rem,calc(100vw-2rem))] rounded-panel border border-line bg-abyss/95 p-4 shadow-2xl backdrop-blur-xl lg:bottom-20 lg:right-6"
        >
          {outcome && outcome.status !== "failed" ? (
            <Resolved outcome={outcome} onReset={reset} onClose={close} />
          ) : (
            <form onSubmit={onSubmit} className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <Label>Send feedback</Label>
                <button
                  type="button"
                  onClick={close}
                  aria-label="Close feedback"
                  className="text-ink-faint transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma"
                >
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    className="size-3.5"
                  >
                    <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
                  </svg>
                </button>
              </div>

              <fieldset className="flex flex-wrap gap-1.5">
                <legend className="sr-only">What kind of feedback is this?</legend>
                {FEEDBACK_KINDS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setKind(option)}
                    aria-pressed={kind === option}
                    className={cn(
                      "rounded-chip border px-2 py-1 text-[0.6875rem] transition-colors",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma",
                      kind === option
                        ? "border-plasma/40 bg-plasma/12 text-plasma"
                        : "border-line text-ink-faint hover:border-line-bright hover:text-ink-dim",
                    )}
                  >
                    {FEEDBACK_LABEL[option]}
                  </button>
                ))}
              </fieldset>

              <label className="sr-only" htmlFor="feedback-message">
                Your feedback
              </label>
              <textarea
                id="feedback-message"
                ref={textareaRef}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={4}
                placeholder="What happened, and what did you expect instead?"
                className="w-full resize-none rounded-card border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus-visible:border-plasma/50 focus-visible:outline-none"
              />

              {outcome?.status === "failed" && (
                <p className="text-xs text-danger">{outcome.error}</p>
              )}

              {/* Says what is attached before it is sent. Quietly collecting the
                  page and user agent would be a surprise; stating it is not. */}
              <p className="text-[0.6875rem] leading-relaxed text-ink-faint">
                The current page and build identifier are attached so the report can be
                traced.
              </p>

              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={busy || message.trim() === ""}
              >
                {busy ? "Sending…" : "Send"}
              </Button>
            </form>
          )}
        </div>
      )}
    </>
  );
}

function Resolved({
  outcome,
  onReset,
  onClose,
}: {
  outcome: FeedbackOutcome;
  onReset: () => void;
  onClose: () => void;
}) {
  if (outcome.status === "sent") {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-ink">Thank you — that came through.</p>
        <p className="text-xs text-ink-faint">Alpha reports are read individually.</p>
        <div className="flex gap-2">
          <Button variant="surface" size="sm" onClick={onReset}>
            Send another
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    );
  }

  if (outcome.status === "redirected") {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-ink">Opened the feedback form in a new tab.</p>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    );
  }

  // Unconfigured: show the report rather than pretending it was delivered.
  const text = formatReport(
    outcome.status === "unconfigured" ? outcome.report : outcome.report,
  );
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-ink">No feedback channel is configured yet.</p>
      <p className="text-xs text-ink-faint">
        Your report is below — copy it and send it to the team directly. Nothing was lost.
      </p>
      <textarea
        readOnly
        value={text}
        rows={7}
        className="w-full resize-none rounded-card border border-line bg-surface px-3 py-2 font-mono text-[0.6875rem] text-ink-dim"
        onFocus={(event) => event.currentTarget.select()}
      />
      <div className="flex gap-2">
        <Button
          variant="surface"
          size="sm"
          onClick={() => void navigator.clipboard?.writeText(text)}
        >
          Copy
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}
