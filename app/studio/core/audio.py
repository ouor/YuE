"""Small FFmpeg/soundfile helpers for previews and reference clips."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import soundfile as sf

SAMPLE_RATE = 48000


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _run(command):
    result = subprocess.run(command, capture_output=True, timeout=600, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-800:])


def write_flac(path, audio, sample_rate=SAMPLE_RATE):
    sf.write(Path(path), np.asarray(audio), sample_rate, subtype="PCM_24")
    return Path(path)


def make_preview(source, target):
    """Encode a web preview; returns None when FFmpeg is unavailable."""
    if not ffmpeg_available():
        return None
    _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(source), "-codec:a", "libmp3lame", "-b:a", "192k",
          str(target)])
    return Path(target)


def duration(path):
    path = Path(path)
    try:
        return float(sf.info(path).duration)
    except RuntimeError:
        pass
    if shutil.which("ffprobe"):
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                                capture_output=True, timeout=60, check=False)
        if not result.returncode:
            return float(json.loads(result.stdout)["format"]["duration"])
    return None


def clip(source, target, start=0.0, length=None):
    """Cut [start, start+length) into a 48 kHz stereo WAV for transcription and A/B playback."""
    if start < 0 or (length is not None and length <= 0):
        raise ValueError("Clip start must be >= 0 and length > 0")
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg is required to read reference audio; install it and add it to PATH")
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(source)]
    if length is not None:
        command += ["-t", f"{length:.3f}"]
    command += ["-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), str(target)]
    _run(command)
    return Path(target)


def load_mono(path, sample_rate=16000):
    """Mono float32 at `sample_rate` (speech recognition input)."""
    from scipy.signal import resample_poly
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if rate != sample_rate:
        from math import gcd
        g = gcd(rate, sample_rate)
        data = resample_poly(data, sample_rate // g, rate // g).astype(np.float32)
    return data
