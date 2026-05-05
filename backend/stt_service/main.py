from fastapi import FastAPI, WebSocket, Query
from fastapi.datastructures import UploadFile
from fastapi import File
import vosk
try:
    import whisper  # optional dependency for Whisper engine
except Exception as e:
    whisper = None
import json
import numpy as np
from pathlib import Path

app = FastAPI(title="STT Service")

MODEL_PATH = Path(__file__).resolve().parent / "vosk-model-small-ru-0.22"
_vosk_model = None


def get_vosk_model():
    global _vosk_model
    if _vosk_model is None:
        _vosk_model = vosk.Model(str(MODEL_PATH))
    return _vosk_model


@app.post("/transcribe")
async def transcribe(
    engine: str = Query(default="vosk"),
    model_size: str = Query(default="base"),
    file: UploadFile = File(default=...),
):
    audio_bytes = await file.read()
    if engine == "whisper":
        try:
            import whisper as _w
        except Exception as e:
            return {"error": "whisper package not installed: %s" % str(e)}
        # Load Whisper model based on requested size
        model = _w.load_model(model_size)
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        result = model.transcribe(audio_np, language="ru", fp16=False, initial_prompt="хэштег, хештег, хештэг")
        return {"text": result["text"]}
    rec = vosk.KaldiRecognizer(get_vosk_model(), 16000)
    rec.AcceptWaveform(audio_bytes)
    return json.loads(rec.FinalResult())


@app.websocket("/stream")
async def stream(
    ws: WebSocket, 
    engine: str = Query(default="vosk"),
    model: str = Query(default="vosk-model-small-ru-0.22"),
    model_size: str = Query(default="base")
    ):
    await ws.accept()
    rec = vosk.KaldiRecognizer(get_vosk_model(), 16000)
    async for data in ws.iter_bytes():
        if rec.AcceptWaveform(data):
            await ws.send_text(rec.Result())
        else:
            await ws.send_text(rec.PartialResult())


@app.get("/health")
def health():
    return {"status": "ok", "service": "stt"}
