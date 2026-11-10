/**
 * The buttons she can answer one of OpenStall's messages with, as WhatsApp shows them under it: tapping one sends its
 * title as her reply. `onChoose`: on her own demo phone, for the newest message only (WhatsApp takes each tap once);
 * without it, as when watching her chat, they are shown as they look on her phone.
 */
export function ReplyButtons({
  titles,
  onChoose,
  busy = false,
}: {
  titles: string[] | undefined;
  onChoose?: (title: string) => void;
  busy?: boolean;
}) {
  if (!titles?.length) return null;
  return (
    <div
      role="group"
      aria-label={onChoose ? "Answer with a button" : "Buttons under this message on WhatsApp"}
      className="mt-1.5 flex max-w-[85%] flex-wrap gap-1.5"
    >
      {titles.map((title) =>
        onChoose ? (
          <button
            key={title}
            type="button"
            dir="auto"
            disabled={busy}
            onClick={() => onChoose(title)}
            className="lift rounded-full border border-accent bg-surface px-3 py-1 text-sm font-medium text-accent hover:bg-accent-soft disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {title}
          </button>
        ) : (
          <span
            key={title}
            dir="auto"
            className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-muted"
          >
            {title}
          </span>
        ),
      )}
    </div>
  );
}
