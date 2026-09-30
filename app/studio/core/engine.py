"""GPU owner: loads YuE2, SheetSage2 and Qwen3-ASR lazily and runs them one job at a time."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import gc
import importlib.util
from pathlib import Path
import threading
import time

import numpy as np

from .jobs import Cancelled, TokenCounter


@dataclass
class Rendered:
    audio: np.ndarray
    latents: np.ndarray
    semantic_tokens: list
    truncated: dict
    timing: dict


class Engine:
    """Only one model holds the GPU at a time; a 24 GB card cannot host both."""

    def __init__(self, settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._pipe = None
        self._transcriber = None
        self.busy: str | None = None

    # -- lifecycle ------------------------------------------------------------
    @contextmanager
    def gpu(self, label):
        with self._lock:
            self.busy = label
            try:
                yield self
            finally:
                self.busy = None

    def status(self):
        import torch
        device = None
        if torch.cuda.is_available():
            index = torch.cuda.current_device()
            properties = torch.cuda.get_device_properties(index)
            device = {"name": properties.name, "memory_gib": round(properties.total_memory / 2**30, 1),
                      "allocated_gib": round(torch.cuda.memory_allocated(index) / 2**30, 2)}
        return {"busy": self.busy, "yue2_loaded": self._pipe is not None,
                "transcriber_loaded": self._transcriber is not None, "cuda": device,
                "torch": torch.__version__, "model": self.settings.model, "vae": self.settings.vae,
                "transcriber": self.settings.transcriber, "lyrics_asr": self.settings.lyrics_asr,
                "lyrics_available": self.lyrics_available}

    def pipeline(self):
        if self._pipe is None:
            from yue2 import YuE2Pipeline
            self._pipe = YuE2Pipeline.from_pretrained(
                self.settings.model, vae=self.settings.vae, device=self.settings.device,
                local_files_only=self.settings.offline, progress=False)
        return self._pipe

    def _free_cuda(self):
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _park_transcriber(self):
        if self._transcriber is not None:
            self._transcriber.to("cpu")
            self._free_cuda()

    def close(self):
        with self._lock:
            if self._pipe is not None:
                self._pipe.close()
            self._pipe, self._transcriber = None, None
            self._free_cuda()

    # -- YuE2 stages ----------------------------------------------------------
    def plan(self, request, ctx):
        """Return a SymbolicPlan (or the provided-score plan) for a SongRequest."""
        self._park_transcriber()
        pipe = self.pipeline()
        return pipe.plan(request=request, cancelled=ctx.cancelled, on_token=TokenCounter(ctx, "plan"))

    def render(self, plan, ctx):
        """Semantic tokens → acoustic latents → 48 kHz stereo audio for an existing plan."""
        self._park_transcriber()
        pipe = self.pipeline()
        started = time.perf_counter()
        ctx.stage("compose")
        semantic = pipe.generate_semantic(plan, cancelled=ctx.cancelled, on_token=TokenCounter(ctx, "compose"))
        ctx.check()
        ctx.stage("render")
        synth_started = time.perf_counter()
        latents = pipe.synthesize(semantic, cancelled=ctx.cancelled)
        ctx.check()
        decode_started = time.perf_counter()
        audio = pipe.decode(latents)
        timing = {"semantic": semantic.timing, "synthesize_seconds": decode_started - synth_started,
                  "decode_seconds": time.perf_counter() - decode_started,
                  "render_seconds": time.perf_counter() - started}
        return Rendered(audio, latents, semantic.tokens, {"abc": plan.truncated, "semantic": semantic.truncated}, timing)

    # -- SheetSage2 -----------------------------------------------------------
    def transcriber(self):
        if self._transcriber is None:
            from transformers import AutoModel
            kwargs = {"trust_remote_code": True, "local_files_only": self.settings.offline}
            if self.settings.transcriber_revision:
                kwargs.update(revision=self.settings.transcriber_revision,
                              code_revision=self.settings.transcriber_revision)
            self._transcriber = AutoModel.from_pretrained(self.settings.transcriber, **kwargs).eval()
        return self._transcriber

    def transcribe(self, audio_path, output_dir, *, melody_only, ctx):
        import torch
        if self._pipe is not None:
            self._pipe.close()          # drop YuE2 weights from the GPU; reloaded lazily
            self._free_cuda()
        model = self.transcriber()
        device = str(self.settings.device)
        cuda = torch.cuda.is_available() and (device == "auto" or device.startswith("cuda"))
        model.to("cuda" if cuda else "cpu")

        def progress(report):
            if ctx.cancelled():
                raise Cancelled()
            ctx.emit("transcribe", **{k: v for k, v in report.items() if isinstance(v, (int, float, str))})

        try:
            return model.transcribe(str(audio_path), output_dir=str(output_dir), melody_only=melody_only,
                                    dtype="bf16" if cuda else "fp32", progress=progress)
        finally:
            model.to("cpu")
            self._free_cuda()

    # -- Qwen3-ASR ------------------------------------------------------------
    @property
    def lyrics_available(self):
        """qwen-asr is installed, and the models are local or may be downloaded."""
        if importlib.util.find_spec("qwen_asr") is None:
            return False
        local = all(Path(p).is_dir() for p in (self.settings.lyrics_asr, self.settings.lyrics_aligner))
        return local or not self.settings.offline

    @contextmanager
    def listener(self):
        """Yield recognize(clips, language, timestamps) with Qwen3-ASR loaded; unloaded afterwards.

        Loaded per use (about 6 GB, ten seconds): it runs rarely and YuE2 needs the room.
        """
        import torch
        from qwen_asr import Qwen3ASRModel
        if self._pipe is not None:
            self._pipe.close()          # reloaded lazily, as for SheetSage2
        self._park_transcriber()
        device = str(self.settings.device)
        cuda = torch.cuda.is_available() and (device == "auto" or device.startswith("cuda"))
        options = dict(dtype=torch.bfloat16 if cuda else torch.float32, device_map="cuda:0" if cuda else "cpu",
                       local_files_only=self.settings.offline)
        model = Qwen3ASRModel.from_pretrained(self.settings.lyrics_asr, forced_aligner=self.settings.lyrics_aligner,
                                              forced_aligner_kwargs=options, max_new_tokens=1024, **options)

        def recognize(clips, language, timestamps):
            results = []
            for clip in clips:
                result = model.transcribe((clip, 16000), language=language, return_time_stamps=timestamps)[0]
                items = [(item.text, item.start_time, item.end_time) for item in (result.time_stamps or [])]
                results.append((result.language, result.text, items))
            return results

        try:
            yield recognize
        finally:
            model = None                 # drop the weights before emptying the CUDA cache
            self._free_cuda()
