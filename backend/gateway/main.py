import logging
from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
import asyncio
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Use environment variables for service URLs, with defaults for local dev
import os

NOTES_URL  = os.getenv("VOICENOTEB_GW_NOTES_URL", "http://127.0.0.1:8002")
SEARCH_URL = os.getenv("VOICENOTEB_GW_SEARCH_URL", "http://127.0.0.1:8003")


class NoteCreate(BaseModel):
    text: str
    engine: str = "vosk"


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}


@app.post("/api/notes")
async def create_note(payload: NoteCreate):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{NOTES_URL}/notes", json=payload.model_dump())
    return r.json()


@app.get("/api/notes")
async def list_notes():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{NOTES_URL}/notes")
    return r.json()


@app.get("/api/notes/by-date")
async def notes_by_date(date_str: str):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{NOTES_URL}/notes/by-date", params={"date_str": date_str})
    return r.json()


@app.get("/api/notes/{filename}")
async def get_note(filename: str):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{NOTES_URL}/notes/{filename}")
    return r.json()


@app.delete("/api/notes/{filename}", status_code=204)
async def delete_note(filename: str):
    async with httpx.AsyncClient() as c:
        await c.delete(f"{NOTES_URL}/notes/{filename}")


@app.get("/api/search")
async def search(q: str):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{SEARCH_URL}/search", params={"q": q})
    return r.json()


@app.websocket("/api/stream")
async def stream_proxy(ws: WebSocket, engine: str = Query(default="vosk")):
    import websockets as _ws
    await ws.accept()
    uri = f"ws://127.0.0.1:8001/stream?engine={engine}"
    try:
        async with _ws.connect(uri) as stt_ws:
            async def to_stt():
                try:
                    async for data in ws.iter_bytes():
                        await stt_ws.send(data)
                except Exception:
                    pass

            async def from_stt():
                try:
                    async for msg in stt_ws:
                        await ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(to_stt(), from_stt())
    except Exception as e:
        print(f"WebSocket proxy error: {e}")


@app.get("/app", response_class=HTMLResponse)
def web_client():
    html_path = Path(__file__).resolve().parent / "index.html"
    return html_path.read_text(encoding="utf-8")
