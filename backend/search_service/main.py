from fastapi import FastAPI
from pathlib import Path
import sqlite3

app = FastAPI(title="Search Service")
NOTES_DIR = Path(__file__).resolve().parent.parent.parent / "notes"
DB_PATH = str(Path(__file__).resolve().parent / "search_index.db")

def rebuild_index():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(filename, content)")
    conn.execute("DELETE FROM notes_fts")
    for f in NOTES_DIR.glob("*.md"):
        conn.execute("INSERT INTO notes_fts VALUES (?, ?)",
                     (f.name, f.read_text(encoding="utf-8")))
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    NOTES_DIR.mkdir(exist_ok=True)
    rebuild_index()

@app.get("/search")
def search(q: str):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT filename FROM notes_fts WHERE notes_fts MATCH ? ORDER BY rank", (q,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]

@app.get("/rebuild")
def rebuild():
    rebuild_index()
    return {"status": "rebuilt"}

@app.get("/health")
def health():
    return {"status": "ok", "service": "search"}
