import importlib.util
import os
import tempfile
import wave


def available() -> bool:
    return (
        importlib.util.find_spec("faster_whisper") is not None
        and importlib.util.find_spec("sounddevice") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def missing() -> list:
    needed = {
        "faster_whisper": "faster-whisper",
        "sounddevice": "sounddevice",
        "numpy": "numpy",
    }
    return [pkg for mod, pkg in needed.items() if importlib.util.find_spec(mod) is None]


def record(path: str, seconds: int = 5, samplerate: int = 16000) -> str:
    import numpy as np
    import sounddevice as sd

    frames = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(samplerate)
        fh.writeframes(np.asarray(frames, dtype="int16").tobytes())
    return path


def transcribe(path: str, model_size: str = "base") -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(path)
    return " ".join(segment.text.strip() for segment in segments).strip()


def record_and_transcribe(seconds: int = 5, model_size: str = "base") -> str:
    handle, path = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    try:
        record(path, seconds)
        return transcribe(path, model_size)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
