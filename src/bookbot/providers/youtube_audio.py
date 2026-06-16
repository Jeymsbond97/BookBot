"""YouTube audio provider — search + download + compress + split (keyless).

  1. ``search_candidates(query)`` — ``ytsearchN:<query> audiokitob`` via yt-dlp
     (flat extraction = fast, metadata only): returns video candidates
     (id, title, duration, uploader) so the user can pick.
  2. ``download_audio(video_id)`` — download the best audio track, compress it hard
     with ffmpeg (mono, low bitrate MP3 — keeps files small), and if it's still
     over Telegram's send cap, split it into parts (1/3, 2/3, …) with ffmpeg.
     Returns a list of local file paths (one per part) for the bot to send.

Audio files are never stored in Supabase (only an optional Telegram file_id is
cached elsewhere); these temp files live in a caller-managed temp dir.
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

log = logging.getLogger(__name__)

name = "youtube_audio"
fmt = "mp3"

_MAX_CANDIDATES = 6
# Plausible audiobook length: 3 min .. 24 h. Filters out clips / livestreams.
_MIN_DURATION = 180
_MAX_DURATION = 24 * 3600


@dataclass(slots=True)
class AudioCandidate:
    video_id: str
    title: str
    duration: int  # seconds (0 if unknown)
    uploader: str | None = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "?"
        h, rem = divmod(self.duration, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def search_candidates(query: str, limit: int = 5) -> list[AudioCandidate]:
    """Return YouTube audio candidates for ``query`` (metadata only, no download)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "default_search": "ytsearch",
        "skip_download": True,
    }
    out: list[AudioCandidate] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{_MAX_CANDIDATES}:{query} audiokitob",
                                    download=False)
        for e in (info or {}).get("entries", []) or []:
            if not e or not e.get("id"):
                continue
            dur = int(e.get("duration") or 0)
            if dur and not (_MIN_DURATION <= dur <= _MAX_DURATION):
                continue
            out.append(
                AudioCandidate(
                    video_id=e["id"],
                    title=e.get("title") or "Audio",
                    duration=dur,
                    uploader=e.get("uploader") or e.get("channel"),
                )
            )
    except Exception:
        log.warning("yt-dlp search failed for %r", query, exc_info=True)
        return []
    return out[:limit]


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _split(path: Path, workdir: Path, max_bytes: int) -> list[Path]:
    """Split an oversized MP3 into <= max_bytes parts with ffmpeg (no re-encode)."""
    size = path.stat().st_size
    duration = _ffprobe_duration(path)
    if duration <= 0:
        return [path]
    # Number of parts needed (95% headroom for container overhead), then segment
    # by equal time so each part lands under the cap.
    parts = math.ceil(size / (max_bytes * 0.95))
    seg_seconds = max(int(duration / parts), 60)
    pattern = str(workdir / "part_%03d.mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-f", "segment",
             "-segment_time", str(seg_seconds), "-c", "copy", pattern],
            capture_output=True, timeout=900, check=True,
        )
    except Exception:
        log.warning("ffmpeg split failed for %s", path, exc_info=True)
        return [path]
    # The segment muxer can emit a near-empty trailing chunk — drop such stubs.
    segments = [p for p in sorted(workdir.glob("part_*.mp3")) if p.stat().st_size > 10_000]
    for stub in set(workdir.glob("part_*.mp3")) - set(segments):
        stub.unlink(missing_ok=True)
    return segments or [path]


def download_audio(
    video_id: str, workdir: Path, max_bytes: int, bitrate_kbps: int = 48
) -> list[Path]:
    """Download + compress audio; split if over the cap. Returns part paths in order.

    ``workdir`` is a caller-owned temp dir (the caller deletes it after sending).
    Returns an empty list on failure.
    """
    workdir = Path(workdir)
    # 1) Download a small audio track (prefer low-bitrate so it often needs no
    #    re-encode at all — transcoding hours of audio is the slowest step).
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio[abr<=72]/bestaudio/best",
        "outtmpl": str(workdir / "source.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except Exception:
        log.warning("yt-dlp download failed for %s", video_id, exc_info=True)
        return []

    sources = [p for p in workdir.glob("source.*")]
    if not sources:
        return []
    source = sources[0]

    # 2) FAST PATH: if the download is already small enough and in a Telegram-
    #    friendly audio container, send it as-is — skip the ffmpeg re-encode.
    if source.suffix.lower() in (".m4a", ".mp3", ".aac") and source.stat().st_size <= max_bytes:
        return [source]

    # 3) Otherwise compress hard (mono, low-bitrate MP3) and split if still big.
    audio = workdir / "audio.mp3"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1",
             "-b:a", f"{bitrate_kbps}k", str(audio)],
            capture_output=True, timeout=1800, check=True,
        )
    except Exception:
        log.warning("ffmpeg compress failed for %s", video_id, exc_info=True)
        return []
    source.unlink(missing_ok=True)

    if audio.stat().st_size <= max_bytes:
        return [audio]
    parts = _split(audio, workdir, max_bytes)
    if len(parts) > 1 and parts[0] != audio:
        os.remove(audio)  # free the big combined file once split succeeds
    return parts
