import { FormattedText } from "@/components/formatted-text";

/**
 * What a message to a maker in Urdu, Hindi or Spanish says in English, shown under it for someone who reads only
 * English. The API composes it from the English templates with the same facts (never a translation made at run time),
 * and it is never sent to her.
 */
export function EnglishLine({ text }: { text: string }) {
  return (
    <figure className="mt-2 border-t border-border pt-1.5">
      <figcaption className="text-xs font-medium text-muted">In English</figcaption>
      <p lang="en" dir="ltr" className="break-words whitespace-pre-line">
        <FormattedText text={text} />
      </p>
    </figure>
  );
}
