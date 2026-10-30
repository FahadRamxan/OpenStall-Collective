import { ApiStatus } from "@/components/api-status";

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-6 text-sm text-muted sm:flex-row sm:items-start sm:justify-between sm:gap-6 sm:px-6">
        <p className="font-medium text-foreground">Runs in the PayPal sandbox. No real money moves.</p>
        <ApiStatus />
      </div>
    </footer>
  );
}
