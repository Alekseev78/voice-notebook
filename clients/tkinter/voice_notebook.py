import vosk
import sounddevice as sd
import queue
import json
import os
import sys
import threading
import numpy as np
from datetime import datetime, date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkcalendar import Calendar

# ============= НАСТРОЙКИ =============
if hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "notes"
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_SETTINGS = {
    "engine": "vosk",
    "vosk_model": "vosk-model-small-ru-0.22",
    "whisper_model": "base",
    "whisper_language": "ru",
}


# ============= ДИАЛОГ ПАРАМЕТРОВ =============
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings: dict):
        super().__init__(parent)
        self.title("⚙️ Параметры")
        self.resizable(False, False)
        self.grab_set()
        self.settings = settings.copy()
        self.result = None

        pad = {"padx": 10, "pady": 6}

        tk.Label(self, text="Движок распознавания:", font=("Arial", 10, "bold")).grid(
            row=0, column=0, sticky=tk.W, **pad
        )
        self.engine_var = tk.StringVar(value=self.settings["engine"])
        frame_engine = tk.Frame(self)
        frame_engine.grid(row=0, column=1, sticky=tk.W, **pad)
        tk.Radiobutton(
            frame_engine, text="Vosk (offline, быстро)",
            variable=self.engine_var, value="vosk", command=self._toggle_fields
        ).pack(anchor=tk.W)
        tk.Radiobutton(
            frame_engine, text="Whisper (offline, точнее)",
            variable=self.engine_var, value="whisper", command=self._toggle_fields
        ).pack(anchor=tk.W)

        self.vosk_frame = tk.LabelFrame(self, text="Настройки Vosk", font=("Arial", 9))
        self.vosk_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, **pad)
        tk.Label(self.vosk_frame, text="Папка модели:").grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
        self.vosk_model_var = tk.StringVar(value=self.settings["vosk_model"])
        tk.Entry(self.vosk_frame, textvariable=self.vosk_model_var, width=32).grid(row=0, column=1, padx=6, pady=4)
        tk.Label(self.vosk_frame, text="(папка должна лежать рядом со скриптом)",
                 font=("Arial", 8), fg="gray").grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=6)

        self.whisper_frame = tk.LabelFrame(self, text="Настройки Whisper", font=("Arial", 9))
        self.whisper_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, **pad)
        tk.Label(self.whisper_frame, text="Размер модели:").grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
        self.whisper_model_var = tk.StringVar(value=self.settings["whisper_model"])
        ttk.Combobox(self.whisper_frame, textvariable=self.whisper_model_var,
                     values=["tiny", "base", "small", "medium", "large"],
                     width=10, state="readonly").grid(row=0, column=1, padx=6, pady=4, sticky=tk.W)
        tk.Label(self.whisper_frame, text="Язык:").grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
        self.whisper_lang_var = tk.StringVar(value=self.settings["whisper_language"])
        tk.Entry(self.whisper_frame, textvariable=self.whisper_lang_var, width=8).grid(row=1, column=1, padx=6, pady=4, sticky=tk.W)
        tk.Label(self.whisper_frame, text="(ru, en, de… — пусто = автоопределение)",
                 font=("Arial", 8), fg="gray").grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=6)
        tk.Label(self.whisper_frame, text="⚠ Установка: pip install openai-whisper",
                 font=("Arial", 8), fg="#e67e22").grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=(0, 4))

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        tk.Button(btn_frame, text="✅ Применить", bg="#27ae60", fg="white",
                  font=("Arial", 10), command=self._apply).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_frame, text="❌ Отмена", bg="#e74c3c", fg="white",
                  font=("Arial", 10), command=self.destroy).pack(side=tk.LEFT, padx=8)

        self._toggle_fields()
        self.update_idletasks()
        x = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        y = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{x}+{y}")

    def _toggle_fields(self):
        engine = self.engine_var.get()
        for child in self.vosk_frame.winfo_children():
            try: child.config(state=tk.NORMAL if engine == "vosk" else tk.DISABLED)
            except tk.TclError: pass
        for child in self.whisper_frame.winfo_children():
            try: child.config(state=tk.NORMAL if engine == "whisper" else tk.DISABLED)
            except tk.TclError: pass

    def _apply(self):
        self.result = {
            "engine": self.engine_var.get(),
            "vosk_model": self.vosk_model_var.get().strip(),
            "whisper_model": self.whisper_model_var.get(),
            "whisper_language": self.whisper_lang_var.get().strip(),
        }
        self.destroy()


# ============= КЛАСС ПРИЛОЖЕНИЯ =============
class VoiceNotebook:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Голосовая записная книжка")
        self.root.geometry("1100x700")

        self.settings = DEFAULT_SETTINGS.copy()
        self.is_recording = False
        self.current_text = ""

        self._vosk_model = None
        self._vosk_model_name = None
        self._whisper_model = None
        self._whisper_model_name = None

        self.audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self.rec = None
        self._whisper_frames = []

        self.create_ui()
        self.load_notes()
        self._mark_calendar_dates()

    # ============= VOSK =============
    def _get_vosk_model(self):
        name = self.settings["vosk_model"]
        if self._vosk_model is None or self._vosk_model_name != name:
            model_path = BASE_DIR / name
            if not model_path.exists():
                messagebox.showerror("Ошибка модели Vosk",
                    f"Папка модели не найдена:\n{model_path}")
                return None
            self.status_label.config(text=f"Загрузка Vosk модели: {name}…")
            self.root.update()
            self._vosk_model = vosk.Model(str(model_path))
            self._vosk_model_name = name
        return self._vosk_model

    # ============= WHISPER =============
    def _get_whisper_model(self):
        size = self.settings["whisper_model"]
        if self._whisper_model is None or self._whisper_model_name != size:
            try:
                import whisper as _whisper
            except ImportError:
                messagebox.showerror("Whisper не установлен",
                    "Установите библиотеку:\n\npip install openai-whisper")
                return None
            import whisper as _whisper
            self.status_label.config(text=f"Загрузка Whisper модели: {size}…")
            self.root.update()
            self._whisper_model = _whisper.load_model(size)
            self._whisper_model_name = size
        return self._whisper_model

    # ============= ИНТЕРФЕЙС =============
    def create_ui(self) -> None:
        # ---------- Верхняя панель ----------
        top_frame = tk.Frame(self.root, bg="#2c3e50")
        top_frame.pack(fill=tk.X, padx=10, pady=8)

        self.record_btn = tk.Button(
            top_frame, text="🎤 Начать запись",
            font=("Arial", 13, "bold"), bg="#27ae60", fg="white",
            command=self.toggle_recording, height=2, width=18)
        self.record_btn.pack(side=tk.LEFT, padx=8, pady=8)

        tk.Button(top_frame, text="💾 Сохранить",
            font=("Arial", 11), bg="#3498db", fg="white",
            command=self.save_note, height=2, width=13).pack(side=tk.LEFT, padx=4)

        tk.Button(top_frame, text="🗑️ Очистить",
            font=("Arial", 11), bg="#e74c3c", fg="white",
            command=self.clear_text, height=2, width=11).pack(side=tk.LEFT, padx=4)

        tk.Button(top_frame, text="⚙️ Параметры",
            font=("Arial", 11), bg="#8e44ad", fg="white",
            command=self.open_settings, height=2, width=12).pack(side=tk.LEFT, padx=4)

        self.engine_label = tk.Label(
            top_frame, text="Движок: Vosk",
            font=("Arial", 10, "bold"), bg="#2c3e50", fg="#f1c40f")
        self.engine_label.pack(side=tk.LEFT, padx=12)

        # ---------- Основная область (3 колонки) ----------
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # Левая колонка: календарь
        left_frame = tk.Frame(main_frame, width=220)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left_frame.pack_propagate(False)

        tk.Label(left_frame, text="📅 Календарь",
                 font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 4))

        today = date.today()
        self.calendar = Calendar(
            left_frame,
            selectmode="day",
            year=today.year, month=today.month, day=today.day,
            date_pattern="yyyy-mm-dd",
            locale="ru_RU",
            background="#2c3e50", foreground="white",
            headersbackground="#34495e", headersforeground="white",
            selectbackground="#27ae60", selectforeground="white",
            normalbackground="white", normalforeground="#2c3e50",
            weekendbackground="#f8f9fa", weekendforeground="#e74c3c",
            font=("Arial", 9),
        )
        self.calendar.pack(fill=tk.X)
        self.calendar.bind("<<CalendarSelected>>", self._on_date_selected)

        # Список заметок за выбранную дату
        tk.Label(left_frame, text="Заметки за день:",
                 font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(8, 2))

        cal_list_frame = tk.Frame(left_frame)
        cal_list_frame.pack(fill=tk.BOTH, expand=True)

        cal_sb = tk.Scrollbar(cal_list_frame)
        cal_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.cal_notes_listbox = tk.Listbox(
            cal_list_frame, font=("Courier", 8),
            yscrollcommand=cal_sb.set,
            bg="#f0f4f8", selectbackground="#27ae60")
        self.cal_notes_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cal_sb.config(command=self.cal_notes_listbox.yview)
        self.cal_notes_listbox.bind("<Double-Button-1>", self._open_note_from_calendar)

        self.cal_count_label = tk.Label(left_frame, text="",
                                        font=("Arial", 8), fg="#7f8c8d")
        self.cal_count_label.pack(anchor=tk.W)

        # Центральная колонка: текстовая область
        center_frame = tk.Frame(main_frame)
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        tk.Label(center_frame, text="Распознанный текст:",
                 font=("Arial", 11, "bold")).pack(anchor=tk.W)

        self.text_area = scrolledtext.ScrolledText(
            center_frame, wrap=tk.WORD,
            font=("Arial", 12), bg="#ecf0f1", fg="#2c3e50")
        self.text_area.pack(fill=tk.BOTH, expand=True, pady=4)

        # Правая колонка: все заметки + поиск
        right_frame = tk.Frame(main_frame, width=230)
        right_frame.pack(side=tk.LEFT, fill=tk.Y)
        right_frame.pack_propagate(False)

        tk.Label(right_frame, text="🔍 Поиск:",
                 font=("Arial", 10, "bold")).pack(anchor=tk.W)

        self.search_entry = tk.Entry(right_frame, font=("Arial", 10))
        self.search_entry.pack(fill=tk.X, pady=2)
        self.search_entry.bind("<KeyRelease>", lambda e: self.search_notes())

        tk.Button(right_frame, text="🔄 Обновить",
                  command=self.load_notes).pack(anchor=tk.W, pady=2)

        tk.Label(right_frame, text="Все заметки:",
                 font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))

        all_list_frame = tk.Frame(right_frame)
        all_list_frame.pack(fill=tk.BOTH, expand=True)

        all_sb = tk.Scrollbar(all_list_frame)
        all_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.notes_listbox = tk.Listbox(
            all_list_frame, font=("Courier", 8),
            yscrollcommand=all_sb.set)
        self.notes_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        all_sb.config(command=self.notes_listbox.yview)
        self.notes_listbox.bind("<Double-Button-1>", self.open_note)

        # ---------- Статусная строка ----------
        self.status_label = tk.Label(
            self.root, text="Готов к работе",
            font=("Arial", 9), bg="#34495e", fg="white",
            anchor=tk.W, padx=10)
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)

    # ============= КАЛЕНДАРЬ =============
    def _note_date(self, note_path: Path) -> str:
        """Извлекает дату из имени файла вида note_YYYY-MM-DD_HH-MM-SS.md"""
        try:
            return note_path.stem.split("_")[1]  # 'YYYY-MM-DD'
        except IndexError:
            return ""

    def _mark_calendar_dates(self):
        """Помечает дни в календаре, когда есть заметки."""
        self.calendar.calevent_remove("all")
        dates_with_notes = set()
        for note in OUTPUT_DIR.glob("*.md"):
            d = self._note_date(note)
            if d:
                dates_with_notes.add(d)
        for d_str in dates_with_notes:
            try:
                y, m, day = map(int, d_str.split("-"))
                self.calendar.calevent_create(
                    date(y, m, day), "📝", tags="has_note")
            except ValueError:
                pass
        self.calendar.tag_config("has_note", background="#d5f5e3", foreground="#1e8449")

    def _on_date_selected(self, event=None):
        """Показывает заметки за выбранную дату."""
        selected = self.calendar.get_date()  # 'YYYY-MM-DD'
        self.cal_notes_listbox.delete(0, tk.END)
        notes = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
        found = [n for n in notes if self._note_date(n) == selected]
        for note in found:
            # Показываем только время из имени файла
            parts = note.stem.split("_")
            time_part = parts[2].replace("-", ":") if len(parts) > 2 else note.name
            self.cal_notes_listbox.insert(tk.END, f"🕐 {time_part}  {note.name}")
        count = len(found)
        self.cal_count_label.config(
            text=f"{selected}: {count} заметок" if count else f"{selected}: нет заметок")

    def _open_note_from_calendar(self, event=None):
        """Открывает заметку из списка календаря."""
        selection = self.cal_notes_listbox.curselection()
        if not selection:
            return
        # Извлекаем имя файла из строки списка (последний токен)
        line = self.cal_notes_listbox.get(selection[0])
        filename = line.split()[-1]
        filepath = OUTPUT_DIR / filename
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            self.text_area.delete(1.0, tk.END)
            self.text_area.insert(1.0, content)
            self.current_text = content
            self.status_label.config(text=f"Открыто: {filename}")

    # ============= ПАРАМЕТРЫ =============
    def open_settings(self):
        if self.is_recording:
            messagebox.showwarning("Запись идёт", "Остановите запись перед изменением параметров.")
            return
        dlg = SettingsDialog(self.root, self.settings)
        self.root.wait_window(dlg)
        if dlg.result:
            self.settings.update(dlg.result)
            engine_name = "Vosk" if self.settings["engine"] == "vosk" else "Whisper"
            self.engine_label.config(text=f"Движок: {engine_name}")
            self.status_label.config(text=f"Параметры обновлены. Движок: {engine_name}")

    # ============= ЗАПИСЬ ЗВУКА =============
    def audio_callback_vosk(self, indata, frames, time, status) -> None:
        if status:
            print(f"Статус аудио: {status}")
        self.audio_queue.put(bytes(indata))

    def audio_callback_whisper(self, indata, frames, time, status) -> None:
        if status:
            print(f"Статус аудио: {status}")
        self._whisper_frames.append(indata.copy())

    def toggle_recording(self) -> None:
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self) -> None:
        engine = self.settings["engine"]
        if engine == "vosk":
            model = self._get_vosk_model()
            if model is None:
                return
            self.rec = vosk.KaldiRecognizer(model, 16000)
            while not self.audio_queue.empty():
                self.audio_queue.get_nowait()
            self.is_recording = True
            self.current_text = ""
            self.stream = sd.RawInputStream(
                samplerate=16000, blocksize=8000,
                dtype="int16", channels=1,
                callback=self.audio_callback_vosk)
            self.stream.start()
            threading.Thread(target=self.process_audio_vosk, daemon=True).start()
        else:
            model = self._get_whisper_model()
            if model is None:
                return
            self._whisper_frames = []
            self.is_recording = True
            self.current_text = ""
            self.stream = sd.InputStream(
                samplerate=16000, blocksize=4000,
                dtype="float32", channels=1,
                callback=self.audio_callback_whisper)
            self.stream.start()

        self.record_btn.config(text="⏹️ Остановить запись", bg="#e74c3c")
        self.status_label.config(
            text=f"🎤 Идет запись [{self.settings['engine'].upper()}]... Говорите!")

    def stop_recording(self) -> None:
        self.is_recording = False
        self.record_btn.config(text="🎤 Начать запись", bg="#27ae60")
        if hasattr(self, "stream"):
            self.stream.stop()
            self.stream.close()
        if self.settings["engine"] == "vosk":
            final = json.loads(self.rec.FinalResult())
            if final.get("text"):
                self.current_text += " " + final["text"]
                self.update_text_area()
            self.status_label.config(text="Запись остановлена (Vosk)")
        else:
            self.status_label.config(text="⏳ Whisper обрабатывает аудио…")
            self.root.update()
            threading.Thread(target=self._transcribe_whisper, daemon=True).start()

    def process_audio_vosk(self) -> None:
        while self.is_recording:
            try:
                data = self.audio_queue.get(timeout=0.1)
                if self.rec.AcceptWaveform(data):
                    result = json.loads(self.rec.Result())
                    text = result.get("text", "")
                    if text:
                        self.current_text += " " + text
                        self.update_text_area()
                else:
                    partial = json.loads(self.rec.PartialResult())
                    p = partial.get("partial", "")
                    if p:
                        self.update_text_area(p)
            except queue.Empty:
                continue

    def _transcribe_whisper(self) -> None:
        try:
            import whisper as _whisper
            if not self._whisper_frames:
                self.root.after(0, lambda: self.status_label.config(text="Нет аудио для Whisper"))
                return
            audio_np = np.concatenate(self._whisper_frames, axis=0).flatten().astype(np.float32)
            lang = self.settings["whisper_language"] or None
            result = self._whisper_model.transcribe(audio_np, language=lang, fp16=False)
            text = result.get("text", "").strip()
            if text:
                self.current_text += " " + text
                self.root.after(0, self.update_text_area)
            self.root.after(0, lambda: self.status_label.config(text="Готово (Whisper)"))
        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text=f"Ошибка Whisper: {e}"))

    def update_text_area(self, partial: str = "") -> None:
        self.text_area.delete(1.0, tk.END)
        display = self.current_text.strip()
        if partial:
            display += f" {partial}"
        self.text_area.insert(1.0, display)
        self.text_area.see(tk.END)

    # ============= РАБОТА С ЗАМЕТКАМИ =============
    def save_note(self) -> None:
        text = self.text_area.get(1.0, tk.END).strip()
        if not text:
            messagebox.showwarning("Пусто", "Нет текста для сохранения")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = OUTPUT_DIR / f"note_{timestamp}.md"
        markdown = (
            f"# Заметка от {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"{text}\n\n---\n"
            f"*Создано голосом через {self.settings['engine'].capitalize()}*\n"
        )
        filename.write_text(markdown, encoding="utf-8")
        self.status_label.config(text=f"✅ Сохранено: {filename.name}")
        self.load_notes()
        self._mark_calendar_dates()   # обновить отметки на календаре
        self._on_date_selected()      # обновить список за текущую дату
        messagebox.showinfo("Успех", f"Заметка сохранена:\n{filename.name}")

    def clear_text(self) -> None:
        if messagebox.askyesno("Очистить", "Очистить текст?"):
            self.text_area.delete(1.0, tk.END)
            self.current_text = ""
            self.status_label.config(text="Текст очищен")

    def load_notes(self) -> None:
        self.notes_listbox.delete(0, tk.END)
        notes = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
        for note in notes:
            self.notes_listbox.insert(tk.END, note.name)
        self.status_label.config(text=f"Загружено заметок: {len(notes)}")

    def search_notes(self) -> None:
        query = self.search_entry.get().lower()
        self.notes_listbox.delete(0, tk.END)
        notes = sorted(OUTPUT_DIR.glob("*.md"), reverse=True)
        found = 0
        for note in notes:
            content = note.read_text(encoding="utf-8").lower()
            if query in content or query in note.name.lower():
                self.notes_listbox.insert(tk.END, note.name)
                found += 1
        self.status_label.config(text=f"Найдено: {found}")

    def open_note(self, event) -> None:
        selection = self.notes_listbox.curselection()
        if not selection:
            return
        filename = self.notes_listbox.get(selection[0])
        content = (OUTPUT_DIR / filename).read_text(encoding="utf-8")
        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(1.0, content)
        self.current_text = content
        self.status_label.config(text=f"Открыто: {filename}")


# ============= ЗАПУСК =============
if __name__ == "__main__":
    root = tk.Tk()
    app = VoiceNotebook(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
