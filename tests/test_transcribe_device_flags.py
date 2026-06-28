import sys
import types
from pathlib import Path

import pytest

from videotool.ai.faster_whisper_adapter import FasterWhisperTranscriber
from videotool.core.errors import DependencyError


def _install_fake_whisper(monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
    """Stub `faster_whisper.WhisperModel` so the adapter never downloads or imports the
    real package; record the constructor args to assert GPU flags propagate."""

    class _FakeSegment:
        start, end, text = 0.0, 1.0, "x"

    class _FakeInfo:
        language = "vi"

    class _FakeWhisperModel:
        def __init__(self, model_ref, device="cpu", compute_type="int8"):
            captured["model_ref"] = model_ref
            captured["device"] = device
            captured["compute_type"] = compute_type

        def transcribe(self, audio, language=None, beam_size=5):
            return [_FakeSegment()], _FakeInfo()

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)


def test_gpu_flags_propagate_to_whisper_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    _install_fake_whisper(monkeypatch, captured)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"fake")

    transcriber = FasterWhisperTranscriber(model_path="large-v3", device="cuda", compute_type="float16")
    transcriber.transcribe(audio)

    assert captured["model_ref"] == "large-v3"
    assert captured["device"] == "cuda"
    assert captured["compute_type"] == "float16"


def test_defaults_are_cpu_int8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    _install_fake_whisper(monkeypatch, captured)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"fake")
    # A local path that exists passes the guard; defaults must stay cpu/int8.
    model_dir = tmp_path / "local-model"
    model_dir.mkdir()

    transcriber = FasterWhisperTranscriber(model_path=model_dir)
    transcriber.transcribe(audio)

    assert captured["device"] == "cpu"
    assert captured["compute_type"] == "int8"


def test_bare_model_id_does_not_require_existing_path() -> None:
    # A HuggingFace id has no separator; constructing must not raise even though it is not on disk.
    FasterWhisperTranscriber(model_path="large-v3")


def test_missing_explicit_path_raises() -> None:
    with pytest.raises(DependencyError):
        FasterWhisperTranscriber(model_path="/no/such/model")
