from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import re

app = FastAPI(title="Notes Service")
import os

# Store notes in a dedicated data directory inside the service
NOTES_DIR = Path(__file__).resolve().parent / "data"
NOTES_DIR.mkdir(exist_ok=True)


class NoteCreate(BaseModel):
    text: str
    engine: str = "vosk"


def extract_hashtags(text: str) -> str:
    """Извлекает слова после слова 'хэштег' или '#слово' из текста."""
    tags = []

    # Вариант 1: слово "хэштег" (или "хештег") followed by слово
    voice_tags = re.findall(r'х[еэ]штег\s+(\w+)', text, re.IGNORECASE)
    tags.extend(voice_tags)

    # Вариант 2: классический #тег
    symbol_tags = re.findall(r'#(\w+)', text)
    tags.extend(symbol_tags)

    # Убрать дубли, оставить порядок
    seen = set()
    unique = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)

    return "_".join(unique[:5])  # максимум 5 тегов в имени


def safe_filename(name: str) -> str:
    """Убрать символы запрещённые в именах файлов Windows."""
    return re.sub(r'[\\/:*?"<>|]', '', name)


@app.post("/notes", status_code=201)
def create_note(payload: NoteCreate):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tags = extract_hashtags(payload.text)

    if tags:
        base_name = f"note_{ts}_{safe_filename(tags)}.md"
    else:
        base_name = f"note_{ts}.md"

    fname = NOTES_DIR / base_name
    fname.write_text(
        f"# Заметка от {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"{payload.text}\n\n---\n*Создано через {payload.engine}*\n",
        encoding="utf-8"
    )
    return {"filename": fname.name}


@app.get("/notes")
def list_notes():
    return [f.name for f in sorted(NOTES_DIR.glob("*.md"), reverse=True)]


@app.get("/notes/by-date")
def notes_by_date(date_str: str):
    return sorted(
        [f.name for f in NOTES_DIR.glob(f"note_{date_str}*.md")],
        reverse=True
    )


@app.get("/notes/{filename}")
def get_note(filename: str):
    path = NOTES_DIR / filename
    return {"content": path.read_text(encoding="utf-8")}


@app.delete("/notes/{filename}", status_code=204)
def delete_note(filename: str):
    (NOTES_DIR / filename).unlink(missing_ok=True)


@app.get("/health")
def health():
    return {"status": "ok", "service": "notes"}
