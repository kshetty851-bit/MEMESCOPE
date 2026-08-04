import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Settings — MEMESCOPE",
};

/**
 * Placeholder for account settings.
 *
 * Exists for the same reason the wallet route does: the nav has four
 * destinations in the approved V1 architecture, and every one of them should
 * resolve. Alerts and account management land with V1.1.
 */
export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold text-ink">Settings</h1>
      <p className="mt-4 max-w-prose text-ink-dim">
        Nothing to configure yet. Alerts and account management arrive with the
        next release.
      </p>
    </div>
  );
}
