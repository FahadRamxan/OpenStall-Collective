/** A run of WhatsApp's bold: *like this*, on one line. */
const BOLD = /(\*[^*\n]+\*)/g;

/**
 * A message as WhatsApp shows it: *bold* in bold, everything else as written. Its parent keeps the line breaks
 * (`whitespace-pre-line`), as OpenStall's messages put each step and each fact on a line of its own.
 */
export function FormattedText({ text }: { text: string }) {
  return (
    <>
      {text.split(BOLD).map((part, index) =>
        part.length > 2 && part.startsWith("*") && part.endsWith("*") ? (
          <strong key={index} className="font-semibold">
            {part.slice(1, -1)}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  );
}
