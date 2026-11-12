"""When each narration line starts and ends on narration-draft.mp3, from ElevenLabs Scribe's word timings:
video/narration-timecodes.json, and printed.
Run from the repository's root with its venv: .venv/Scripts/python video/tools/timecodes.py"""
import json, re, sys, httpx
from pathlib import Path
from openstall_api.settings import get_settings
sys.stdout.reconfigure(encoding="utf-8")
kit = Path(__file__).resolve().parents[1]
key = get_settings().ELEVENLABS_API_KEY.get_secret_value()
r = httpx.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key},
               data={"model_id": "scribe_v2", "language_code": "en", "timestamps_granularity": "word"},
               files={"file": ("narration.mp3", (kit / "narration-draft.mp3").read_bytes(), "audio/mpeg")}, timeout=300)
r.raise_for_status()
words = [w for w in r.json()["words"] if w.get("type") == "word"]
norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower().replace("í", "i"))
seq = [norm(w["text"]) for w in words]
body = (kit / "narration.md").read_text(encoding="utf-8").split("## Narration", 1)[1].split("\n## ", 1)[0]
rows, pos, section = [], 0, ""
for line in body.splitlines():
    s = line.strip()
    head = re.fullmatch(r"\*\*(.+)\*\*", s)
    if head:
        section = head.group(1); continue
    if not s.startswith("["):
        continue
    tag, _, said = s.partition("]")
    said = said.strip().strip('"')
    tokens = [norm(t) for t in said.split() if norm(t)]
    start = next((i for i in range(pos, len(seq) - 1)
                  if seq[i] == tokens[0] and (len(tokens) == 1 or seq[i + 1] == tokens[1])), None)
    if start is None:
        rows.append({"section": section, "tag": tag + "]", "line": said, "start": None, "end": None}); continue
    end = min(start + len(tokens) - 1, len(words) - 1)
    pos = end + 1
    rows.append({"section": section, "tag": tag + "]", "line": said,
                 "start": round(words[start]["start"], 2), "end": round(words[end]["end"], 2)})
(kit / "narration-timecodes.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
fmt = lambda t: "--" if t is None else f"{int(t // 60)}:{t % 60:04.1f}"
for row in rows:
    print(f"{fmt(row['start']):>7} - {fmt(row['end']):>7}  {row['line'][:80]}")
