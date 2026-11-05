import { languageName } from "@/lib/catalog";

/**
 * What a seller's voice note said, as text: her words as she said them, never translated, marked with their language
 * so a screen reader reads them in it and Urdu runs right to left.
 */
export function VoiceTranscript({ text, language }: { text: string; language?: string | null }) {
  const name = languageName(language ?? null);
  return (
    <figure className="mb-2">
      <figcaption className="text-xs font-medium text-muted">
        {name ? `Voice note in ${name}, as text` : "Voice note, as text"}
      </figcaption>
      <blockquote
        lang={language ?? undefined}
        dir="auto"
        className="mt-1 border-s-2 border-accent/40 ps-2 break-words whitespace-pre-line"
      >
        {text}
      </blockquote>
    </figure>
  );
}
