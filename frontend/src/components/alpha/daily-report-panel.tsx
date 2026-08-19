"use client";

import { useEffect, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * The daily paper-wallet report, as Settings sees it.
 *
 * Read-only by design. Schedule, recipients and credentials are environment
 * configuration on the server, and a toggle here would imply the browser can
 * change them — which it cannot, and should not: a page that offers a switch
 * that silently does nothing is worse than a page that shows the state.
 *
 * The one action is the test send, which is why it exists at all. It proves the
 * SMTP path end to end without waiting for 09:00 and without consuming the
 * scheduled day — the backend records it under a separate `TEST` kind.
 *
 * No secret reaches this component. `/reports/daily/config` returns whether
 * credentials are present, never what they are.
 */

type ReportConfig = {
  enabled: boolean;
  email_configured: boolean;
  recipients: string[];
  hour: number;
  minute: number;
  timezone: string;
};

type SendState = "idle" | "sending" | "sent" | "failed";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-subtle py-2 last:border-0">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="text-xs text-ink-2">{value}</dd>
    </div>
  );
}

export function DailyReportPanel() {
  const [config, setConfig] = useState<ReportConfig | null>(null);
  const [state, setState] = useState<SendState>("idle");
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .get<ReportConfig>("/reports/daily/config")
      .then((next) => {
        if (!cancelled) setConfig(next);
      })
      .catch(() => {
        // A settings panel that cannot read its own config is not an error
        // worth shouting about; it renders as unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function sendTest() {
    if (state === "sending") return;
    setState("sending");
    setDetail(null);
    try {
      const result = await api.post<{ sent: number; failed: number; reason: string | null }>(
        "/reports/daily/test",
        {},
      );
      if (result.sent > 0) {
        setState("sent");
        setDetail(`Delivered to ${result.sent} recipient${result.sent === 1 ? "" : "s"}.`);
      } else {
        setState("failed");
        setDetail(result.reason ?? "The provider accepted nothing.");
      }
    } catch {
      setState("failed");
      setDetail("The request failed. Check the backend logs.");
    }
  }

  if (!config) return null;

  const time = `${String(config.hour).padStart(2, "0")}:${String(config.minute).padStart(2, "0")}`;

  return (
    <Panel density="comfortable">
      <div className="flex flex-col gap-1 pb-3">
        <h2 className="text-sm font-medium text-ink">Daily paper wallet report</h2>
        <p className="text-xs leading-relaxed text-ink-2">
          An emailed summary of the paper wallet — portfolio, today&apos;s trades, open
          positions and data-quality warnings. Configured on the server; shown here so
          the schedule is visible without reading the deployment.
        </p>
      </div>

      <dl className="flex flex-col">
        <Row
          label="Status"
          value={
            <span
              className={cn(
                config.enabled && config.email_configured ? "text-up" : "text-ink-3",
              )}
            >
              {config.enabled
                ? config.email_configured
                  ? "Scheduled"
                  : "Enabled — no mail credentials"
                : "Disabled"}
            </span>
          }
        />
        <Row label="Schedule" value={`Daily · ${time} · ${config.timezone}`} />
        <Row
          label="Recipients"
          value={config.recipients.length ? config.recipients.join(", ") : "None"}
        />
      </dl>

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line-subtle pt-4">
        <button
          type="button"
          onClick={sendTest}
          disabled={state === "sending" || !config.email_configured}
          className={cn(
            "h-8 rounded-md border border-line-control px-3 text-xs text-ink-2",
            "transition-colors duration-[var(--duration-instant)]",
            "hover:border-line-strong hover:text-ink",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {state === "sending" ? "Sending…" : "Send test email"}
        </button>

        {detail ? (
          <span
            role="status"
            className={cn("text-xs", state === "failed" ? "text-down" : "text-up")}
          >
            {detail}
          </span>
        ) : null}

        {!config.email_configured ? (
          <span className="text-xs text-ink-3">
            Set SMTP_HOST and SMTP_USERNAME to enable delivery.
          </span>
        ) : null}
      </div>
    </Panel>
  );
}
