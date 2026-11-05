"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent } from "react";

import { Badge } from "@/components/badge";
import { errorMessage } from "@/lib/api";
import { fetchSample, type ChatSamples } from "@/lib/chats";

type Recording = { recorder: MediaRecorder; started: number };

/** The most files one message carries, as the API takes them. */
const MAX_FILES = 5;

/** True when this browser can record from the microphone. Without it, a voice note can still be uploaded. */
function canRecord(): boolean {
  return typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;
}

/** Nothing to follow: whether the browser can record does not change while the page is open. */
function subscribeToNothing(): () => void {
  return () => {};
}

/**
 * Whether this browser can record. False on the server, which cannot know, and while the page hydrates, so the
 * browser's first render matches the server's HTML; the browser's own answer right after.
 */
function useCanRecord(): boolean {
  return useSyncExternalStore(subscribeToNothing, canRecord, () => false);
}

const BUTTON =
  "inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border border-border bg-surface px-4 text-sm font-semibold hover:bg-background focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/** The test-mode samples, each with its button's words and the name its file is sent under. */
const SAMPLES = [
  { key: "photo", label: "Attach the sample photo", file: "sample-photo.png", what: "photo" },
  { key: "voice_note", label: "Attach the sample voice note", file: "sample-voice-note.wav", what: "voice note" },
] as const;

/**
 * The seller's side of the web chat: a message, photos, and a voice note recorded in the browser (or uploaded, where
 * the browser cannot record). `onSend` says whether it went; on failure everything stays, ready to send again.
 * `samples`, in test mode: the API paths of a sample photo and voice note to attach, so a listing can be tried without
 * a camera or a microphone (test mode reads them as Amina's cushion cover, and her words in Urdu).
 */
export function ChatComposer({
  onSend,
  busy,
  samples = null,
}: {
  onSend: (text: string, files: File[]) => Promise<boolean>;
  busy: boolean;
  samples?: ChatSamples | null;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [sampleProblem, setSampleProblem] = useState<string | null>(null);
  const [fetchingSample, setFetchingSample] = useState(false);
  const recordable = useCanRecord();
  const form = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (!recording) return;
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - recording.started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [recording]);

  function add(picked: FileList | null) {
    if (!picked) return;
    const chosen = Array.from(picked); // copied now: clearing the input afterwards empties the live FileList
    setFiles((current) => [...current, ...chosen].slice(0, MAX_FILES));
  }

  async function attachSample(path: string, name: string, what: string) {
    setSampleProblem(null);
    setFetchingSample(true);
    try {
      const sample = await fetchSample(path, name);
      setFiles((current) => [...current, sample].slice(0, MAX_FILES));
    } catch (error) {
      setSampleProblem(`The sample ${what} could not be attached: ${errorMessage(error)}`);
    } finally {
      setFetchingSample(false);
    }
  }
  const offered = SAMPLES.flatMap((sample) => {
    const path = samples?.[sample.key];
    return path ? [{ ...sample, path }] : [];
  });

  async function startRecording() {
    setProblem(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => chunks.push(event.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const type = recorder.mimeType || "audio/webm";
        const extension = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        setFiles((current) => [...current, new File(chunks, `voice-note.${extension}`, { type })]);
        setRecording(null);
      };
      recorder.start();
      setSeconds(0);
      setRecording({ recorder, started: Date.now() });
    } catch {
      setProblem("The microphone is not available here. You can upload a voice note instead.");
    }
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (busy || recording || (!text.trim() && files.length === 0)) return;
    if (await onSend(text.trim(), files)) {
      setText("");
      setFiles([]);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, as in WhatsApp; Shift+Enter starts a new line.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form ref={form} onSubmit={submit} aria-label="Send a message" className="border-t border-border bg-surface p-3 sm:p-4">
      {files.length > 0 ? (
        <ul aria-label="Attached" className="mb-3 flex flex-wrap gap-2">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="inline-flex items-center gap-2 rounded-full bg-background py-1 pr-1 pl-3 text-sm"
            >
              <span>{file.type.startsWith("audio/") ? "Voice note" : file.name}</span>
              <button
                type="button"
                onClick={() => setFiles((current) => current.filter((_, at) => at !== index))}
                aria-label={`Remove ${file.type.startsWith("audio/") ? "the voice note" : file.name}`}
                className="grid size-7 place-items-center rounded-full hover:bg-border focus-visible:outline-2 focus-visible:outline-accent"
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <label htmlFor="chat-text" className="sr-only">
        Message
      </label>
      <textarea
        id="chat-text"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        maxLength={4000}
        placeholder="Tell OpenStall about what you make…"
        className="w-full resize-none rounded-2xl border border-border bg-background px-4 py-3 text-base leading-6 focus-visible:outline-2 focus-visible:outline-accent"
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className={BUTTON}>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="sr-only"
            onChange={(event) => {
              add(event.target.files);
              event.target.value = "";
            }}
          />
          Attach a photo
        </label>
        {recordable && !problem ? (
          recording ? (
            <button type="button" onClick={() => recording.recorder.stop()} className={`${BUTTON} text-danger`}>
              <span aria-hidden="true" className="size-2.5 animate-pulse rounded-full bg-danger" />
              Stop recording ({seconds}s)
            </button>
          ) : (
            <button type="button" onClick={startRecording} className={BUTTON}>
              Record a voice note
            </button>
          )
        ) : (
          <label className={BUTTON}>
            <input
              type="file"
              accept="audio/*"
              className="sr-only"
              onChange={(event) => {
                add(event.target.files);
                event.target.value = "";
              }}
            />
            Upload a voice note
          </label>
        )}
        <button
          type="submit"
          disabled={busy || !!recording || (!text.trim() && files.length === 0)}
          className="ml-auto inline-flex min-h-11 items-center rounded-full bg-accent px-6 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Sending…" : "Send"}
        </button>
      </div>
      {offered.length ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-dashed border-border pt-3">
          <Badge tone="warning">Test mode</Badge>
          {offered.map((sample) => (
            <button
              key={sample.key}
              type="button"
              onClick={() => attachSample(sample.path, sample.file, sample.what)}
              disabled={fetchingSample || !!recording || files.length >= MAX_FILES}
              className={`${BUTTON} disabled:cursor-not-allowed disabled:opacity-60`}
            >
              {sample.label}
            </button>
          ))}
        </div>
      ) : null}
      {problem ? (
        <p role="status" className="mt-2 text-sm text-muted">
          {problem}
        </p>
      ) : null}
      {sampleProblem ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {sampleProblem}
        </p>
      ) : null}
    </form>
  );
}
