"""The narration, spoken: each section of video/narration.md through ElevenLabs v3 (its audio tags kept, the
quotes dropped), one MP3 per section, then all of them with short gaps as narration-draft.mp3.

Usage: voice.py [VOICE_ID] [SECTION ...]   (default voice Sarah; default every section)
Run from the repository's root with its venv: .venv/Scripts/python video/tools/voice.py
The key is read through the app's settings (.env) and never printed."""

import json
import re
import subprocess
import sys
from pathlib import Path

import httpx

from openstall_api.settings import get_settings

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parents[1]
OUT = KIT / "voice"
SARAH = "EXAVITQu4vr4xnSDxMaL"


def sections() -> list[tuple[str, str]]:
    text = (KIT / "narration.md").read_text(encoding="utf-8")
    body = text.split("## Narration", 1)[1].split("\n## ", 1)[0]
    found, name, lines = [], None, []
    for line in body.splitlines():
        heading = re.fullmatch(r"\*\*(.+)\*\*", line.strip())
        if heading:
            if name and lines:
                found.append((name, "\n".join(lines)))
            name, lines = heading.group(1), []
        elif line.strip().startswith("["):
            tag, _, said = line.strip().partition("]")
            lines.append(f"{tag}] {said.strip().strip(chr(34))}")
    if name and lines:
        found.append((name, "\n".join(lines)))
    return found


def duration(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(probe.stdout)["format"]["duration"])


def main() -> None:
    voice = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else SARAH
    wanted = set(sys.argv[2:])
    key = get_settings().ELEVENLABS_API_KEY.get_secret_value()
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for index, (name, text) in enumerate(sections(), start=1):
        slug = f"{index:02d}-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        path = OUT / f"{slug}.mp3"
        if not wanted or name in wanted or slug in wanted:
            response = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_v3", "voice_settings": {"stability": 0.5}},
                timeout=180,
            )
            if response.status_code != 200:
                print(f"{slug}: {response.status_code} {response.text[:300]}")
                continue
            path.write_bytes(response.content)
        if path.exists():
            made.append(path)
            print(f"{slug}: {duration(path):5.1f}s  ({len(text)} characters)")
    # All sections with 0.6 s between them, as a draft to listen to.
    gap = OUT / "gap.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.6",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(gap)], check=True)
    listing = OUT / "list.txt"
    listing.write_text("".join(f"file '{p.name}'\nfile '{gap.name}'\n" for p in made), encoding="utf-8")
    draft = KIT / "narration-draft.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "160k", str(draft)], check=True)
    print(f"draft: {draft} {duration(draft):.1f}s")


if __name__ == "__main__":
    main()
