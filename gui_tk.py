from pathlib import Path
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
import multiprocessing as mp
from queue import Empty
from typing import Callable, cast

import common
import gui_common

class ConfigContent(tk.Frame):
    def row(self):
        self._row += 1
        return self._row

    def pick_file(self, stringvar: tk.StringVar, directory: bool = False) -> None:
        if directory:
            file_path = filedialog.askdirectory()
        else:
            file_path = filedialog.askopenfilename()
        if file_path:
            stringvar.set(file_path)

    def update_renderer_options(self, *_args) -> None:
        if self.card_renderer.get() == "resvg":
            self.renderer_path_label.configure(text="Resvg")
            self.renderer_path_entry.configure(textvariable=self.resvg_path)
        else:
            self.renderer_path_label.configure(text="Inkscape")
            self.renderer_path_entry.configure(textvariable=self.inkscape_path)

    def pick_renderer_path(self) -> None:
        path = self.resvg_path if self.card_renderer.get() == "resvg" else self.inkscape_path
        self.pick_file(path)

    def run(self):
        if self.process is not None and self.process.is_alive():
            self.log("stderr", "A recap-maker process is already running.\n")
            return

        try:
            args = gui_common.build_args(self.configuration_values())
        except (KeyError, ValueError, OSError) as exc:
            self.log("stderr", f"Cannot start: {exc}\n")
            return
        self.log_area.delete("1.0", "end")
        self.process = mp.Process(target=gui_common.run_recap_process, args=(args, self.output_queue))
        self.process.start()
        self.run_button.configure(state="disabled")
        self.log("stdout", "Started recap-maker process.\n")
        self.after(50, self.drain_output)

    def log(self, tag: str, message: str) -> None:
        self.log_area.insert("end", message, tag)
        self.log_area.see("end")

    def configuration_values(self) -> dict[str, object]:
        """Read widgets into the canonical shared GUI configuration."""
        return {
            "input_file": self.csv_path.get(), "temp_dir": self.tmp_path.get(),
            "browser": self.browser.get(), "po_token": self.po_token.get(),
            "style": self.style.get(), "size": self.size.get(),
            "auto_height": self.auto_height.get(), "output": self.output_path.get(),
            "fps": self.fps.get(), "fade": self.fade_duration.get(),
            "av1_preset": self.av1_preset.get(), "av1_crf": self.av1_crf.get(),
            "av1_threads": self.av1_threads.get(), "opus_bitrate": self.opus_bitrate.get(),
            "audio_normalization": self.audio_normalization.get(), "jobs": self.jobs.get(),
            "multiprocessing": self.multiprocessing_var.get(), "cleanup": self.cleanup_var.get(),
            "ffmpeg": self.ffmpeg_path.get(), "ffprobe": self.ffprobe_path.get(),
            "yt_dlp": self.yt_dlp_path.get(), "inkscape": self.inkscape_path.get(),
            "card_renderer": self.card_renderer.get(), "resvg": self.resvg_path.get(),
            "recap_mode": self.recap_mode.get(),
        }

    def drain_output(self) -> None:
        while True:
            try:
                tag, message = self.output_queue.get_nowait()
            except Empty:
                break
            self.log(tag, message)

        if self.process is not None and self.process.is_alive():
            self.after(50, self.drain_output)
            return

        if self.process is not None:
            self.process.join()
            status = "completed" if self.process.exitcode == 0 else f"exited with code {self.process.exitcode}"
            self.log("stdout" if self.process.exitcode == 0 else "stderr", f"Recap-maker process {status}.\n")
            self.process = None
        self.run_button.configure(state="normal")

    def __init__(self, master):
        super().__init__(master)
        self._row = 0
        self.output_queue = mp.Queue()
        self.process: mp.Process | None = None

        ttk.Label(self, text="General settings", font=("", 18, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="Input file").grid(column=0, row=self.row(), sticky="e")
        self.csv_path = tk.StringVar()
        self.csv_entry = ttk.Entry(self, textvariable=self.csv_path)
        self.csv_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.csv_path)).grid(column=2, row=self._row)
        ttk.Label(self, text="Temp dir").grid(column=0, row=self.row(), sticky="e")
        self.tmp_path = tk.StringVar(value="temp")
        self.tmp_entry = ttk.Entry(self, textvariable=self.tmp_path)
        self.tmp_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.tmp_path, True)).grid(column=2, row=self._row)
        ttk.Label(self, text="Multiprocessing").grid(column=0, row=self.row(), sticky="e")
        self.multiprocessing_var = tk.BooleanVar(value=True)
        self.multiprocessing_check = ttk.Checkbutton(self, variable=self.multiprocessing_var)
        self.multiprocessing_check.grid(column=1, row=self._row)
        ttk.Label(self, text="Delete temp files").grid(column=0, row=self.row(), sticky="e")
        self.cleanup_var = tk.BooleanVar(value=False)
        self.cleanup_check = ttk.Checkbutton(self, variable=self.cleanup_var)
        self.cleanup_check.grid(column=1, row=self._row)

        ttk.Label(self, text="Executables", font=("", 18, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="Card renderer").grid(column=0, row=self.row(), sticky="e")
        self.card_renderer = tk.StringVar(value="inkscape")
        self.card_renderer_entry = ttk.Combobox(self, textvariable=self.card_renderer, values=["inkscape", "resvg"])
        self.card_renderer_entry.grid(column=1, row=self._row, sticky="ew")
        self.inkscape_path = tk.StringVar(value="inkscape")
        self.resvg_path = tk.StringVar(value="rsvg-convert")
        self.renderer_path_label = ttk.Label(self)
        self.renderer_path_label.grid(column=0, row=self.row(), sticky="e")
        self.renderer_path_entry = ttk.Entry(self)
        self.renderer_path_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=self.pick_renderer_path).grid(column=2, row=self._row)
        self.card_renderer.trace_add("write", self.update_renderer_options)
        self.update_renderer_options()
        ttk.Label(self, text="FFmpeg").grid(column=0, row=self.row(), sticky="e")
        self.ffmpeg_path = tk.StringVar(value="ffmpeg")
        self.ffmpeg_entry = ttk.Entry(self, textvariable=self.ffmpeg_path)
        self.ffmpeg_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.ffmpeg_path)).grid(column=2, row=self._row)
        ttk.Label(self, text="FFprobe").grid(column=0, row=self.row(), sticky="e")
        self.ffprobe_path = tk.StringVar(value="ffmpeg")
        self.ffprobe_entry = ttk.Entry(self, textvariable=self.ffprobe_path)
        self.ffprobe_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.ffprobe_path)).grid(column=2, row=self._row)
        ttk.Label(self, text="yt-dlp").grid(column=0, row=self.row(), sticky="e")
        self.yt_dlp_path = tk.StringVar(value="yt-dlp")
        self.yt_dlp_entry = ttk.Entry(self, textvariable=self.yt_dlp_path)
        self.yt_dlp_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.yt_dlp_path)).grid(column=2, row=self._row)

        ttk.Label(self, text="Download settings", font=("", 18, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="Browser").grid(column=0, row=self.row(), sticky="e")
        self.browser = tk.StringVar()
        self.browser_entry = ttk.Entry(self, textvariable=self.browser)
        self.browser_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="PO Token").grid(column=0, row=self.row(), sticky="e")
        self.po_token = tk.StringVar()
        self.po_token_entry = ttk.Entry(self, textvariable=self.po_token)
        self.po_token_entry.grid(column=1, row=self._row, sticky="ew")

        ttk.Label(self, text="Card settings", font=("", 18, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="Style").grid(column=0, row=self.row(), sticky="e")
        self.style = tk.StringVar(value="70s")
        self.style_entry = ttk.Combobox(self, textvariable=self.style, values=list(common.colours.keys()))
        self.style_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Size override (WxH)").grid(column=0, row=self.row(), sticky="e")
        self.size = tk.StringVar()
        self.size_entry = ttk.Entry(self, textvariable=self.size)
        self.size_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Automatic height").grid(column=0, row=self.row(), sticky="e")
        self.auto_height = tk.StringVar(value="1080")
        self.auto_height_entry = ttk.Entry(self, textvariable=self.auto_height)
        self.auto_height_entry.grid(column=1, row=self._row, sticky="ew")

        ttk.Label(self, text="Recap settings", font=("", 18, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="Output dir").grid(column=0, row=self.row(), sticky="e")
        self.output_path = tk.StringVar(value="output")
        self.output_entry = ttk.Entry(self, textvariable=self.output_path)
        self.output_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.output_path, directory=True)).grid(column=2, row=self._row)
        ttk.Label(self, text="Fade (s)").grid(column=0, row=self.row(), sticky="e")
        self.fade_duration = tk.StringVar(value="0.25")
        self.fade_duration_entry = ttk.Entry(self, textvariable=self.fade_duration)
        self.fade_duration_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="FPS").grid(column=0, row=self.row(), sticky="e")
        self.fps = tk.StringVar(value="60")
        self.fps_entry = ttk.Entry(self, textvariable=self.fps)
        self.fps_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="AV1 preset").grid(column=0, row=self.row(), sticky="e")
        self.av1_preset = tk.StringVar(value="8")
        self.av1_preset_entry = ttk.Entry(self, textvariable=self.av1_preset)
        self.av1_preset_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="AV1 CRF").grid(column=0, row=self.row(), sticky="e")
        self.av1_crf = tk.StringVar(value="30")
        self.av1_crf_entry = ttk.Entry(self, textvariable=self.av1_crf)
        self.av1_crf_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="AV1 threads (0=auto)").grid(column=0, row=self.row(), sticky="e")
        self.av1_threads = tk.StringVar(value="0")
        self.av1_threads_entry = ttk.Entry(self, textvariable=self.av1_threads)
        self.av1_threads_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Opus bitrate").grid(column=0, row=self.row(), sticky="e")
        self.opus_bitrate = tk.StringVar(value="160k")
        self.opus_bitrate_entry = ttk.Entry(self, textvariable=self.opus_bitrate)
        self.opus_bitrate_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Audio normalization").grid(column=0, row=self.row(), sticky="e")
        self.audio_normalization = tk.StringVar(value="two-pass")
        self.audio_normalization_entry = ttk.Combobox(self, textvariable=self.audio_normalization, values=["none", "one-pass", "two-pass"])
        self.audio_normalization_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Render jobs (0=auto)").grid(column=0, row=self.row(), sticky="e")
        self.jobs = tk.StringVar(value="0")
        self.jobs_entry = ttk.Entry(self, textvariable=self.jobs)
        self.jobs_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Recaps").grid(column=0, row=self.row(), sticky="ne")
        self.recap_mode = tk.StringVar(value="both")
        recap_modes = ttk.Frame(self)
        recap_modes.grid(column=1, row=self._row, sticky="w")
        for row, (value, label) in enumerate(gui_common.RECAP_MODES):
            ttk.Radiobutton(recap_modes, text=label, variable=self.recap_mode, value=value).grid(
                column=0, row=row, sticky="w"
            )

        self.run_button = ttk.Button(self, text="Run", command=self.run)
        self.run_button.grid(column=0, row=self.row(), columnspan=3)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL)
        self.log_area = tk.Text(self, wrap=tk.WORD, height=10, yscrollcommand=scrollbar.set)
        self.log_area.grid(column=0, row=self.row(), columnspan=3, sticky="nsew")
        self.log_area.tag_configure("stderr", foreground="#b00020")
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(self._row, weight=2)

    def set_input_path(self, path: Path) -> None:
        self.csv_path.set(str(path))


class ConfigTab(ttk.Frame):
    """Scrollable configuration page whose log expands with the window."""

    def __init__(self, master):
        super().__init__(master)
        self.notebook = cast(ttk.Notebook, master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(column=0, row=0, sticky="nsew")
        scrollbar.grid(column=1, row=0, sticky="ns")

        self.content = ConfigContent(self.canvas)
        self.window = self.canvas.create_window((0, 0), anchor="nw", window=self.content)
        self.content.bind("<Configure>", self.update_scroll_region)
        self.canvas.bind("<Configure>", self.resize_content)
        toplevel = self.winfo_toplevel()
        toplevel.bind_all("<MouseWheel>", self.scroll, add="+")
        toplevel.bind_all("<Button-4>", self.scroll_up, add="+")
        toplevel.bind_all("<Button-5>", self.scroll_down, add="+")

    def update_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def resize_content(self, event) -> None:
        height = max(event.height, self.content.winfo_reqheight())
        self.canvas.itemconfigure(self.window, width=event.width, height=height)

    def is_active(self) -> bool:
        return self.notebook.select() == str(self)

    def scroll(self, event) -> str | None:
        if not self.is_active():
            return None
        if event.delta:
            # macOS trackpads normally report small ±1 deltas, whereas wheel
            # mice commonly report ±120.  Both should produce visible motion.
            units = max(1, abs(event.delta) // 120)
            self.canvas.yview_scroll(-units if event.delta > 0 else units, "units")
        return "break"

    def scroll_up(self, event) -> str | None:
        if not self.is_active():
            return None
        self.canvas.yview_scroll(-1, "units")
        return "break"

    def scroll_down(self, event) -> str | None:
        if not self.is_active():
            return None
        self.canvas.yview_scroll(1, "units")
        return "break"

    def set_input_path(self, path: Path) -> None:
        self.content.set_input_path(path)


class ShowEditor(ttk.Frame):
    """A visual editor for the canonical JSON show schema."""

    FIELDS = gui_common.SHOW_FIELDS
    TABLE_COLUMNS = gui_common.SHOW_TABLE_COLUMNS

    def __init__(self, master, on_saved: Callable[[Path], None]):
        super().__init__(master, padding=8)
        self.on_saved = on_saved
        self.entries: list[dict[str, str]] = []
        self.selected_index: int | None = None
        self.values = {field: tk.StringVar() for field, _ in self.FIELDS}
        self.values["type"].set("video")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="Show editor", font=("", 18, "bold")).grid(column=0, row=0, sticky="w")

        table_frame = ttk.Frame(self)
        table_frame.grid(column=0, row=1, sticky="nsew", pady=(6, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table_frame, columns=self.TABLE_COLUMNS, show="headings", selectmode="browse")
        for column in self.TABLE_COLUMNS:
            self.table.heading(column, text=column.replace("_", " ").title())
            self.table.column(column, width=110, stretch=column in {"country", "artist", "title"})
        self.table.column("artist", width=170)
        self.table.column("title", width=190)
        self.table.grid(column=0, row=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scrollbar.grid(column=1, row=0, sticky="ns")
        horizontal_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        horizontal_scrollbar.grid(column=0, row=1, sticky="ew")
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self.select_entry)

        buttons = ttk.Frame(self)
        buttons.grid(column=0, row=2, sticky="w", pady=(0, 8))
        for label, command in [
            ("New", self.clear_form), ("Add / update", self.save_form), ("Delete", self.delete_entry),
            ("Move up", lambda: self.move_entry(-1)), ("Move down", lambda: self.move_entry(1)),
            ("Load JSON", self.load_json), ("Save JSON", self.save_json),
        ]:
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 6))

        form = ttk.LabelFrame(self, text="Selected entry", padding=8)
        form.grid(column=0, row=3, sticky="ew")
        for column in (1, 3):
            form.columnconfigure(column, weight=1)
        for index, (field, label) in enumerate(self.FIELDS):
            row, column = divmod(index, 2)
            offset = column * 2
            ttk.Label(form, text=label).grid(column=offset, row=row, sticky="e", padx=(0, 6), pady=3)
            if field == "type":
                widget = ttk.Combobox(form, textvariable=self.values[field], values=["video", "audio"], state="readonly")
            else:
                widget = ttk.Entry(form, textvariable=self.values[field])
            widget.grid(column=offset + 1, row=row, sticky="ew", padx=(0, 12), pady=3)

        self.status = tk.StringVar(value="Create entries, then save a JSON show file.")
        ttk.Label(self, textvariable=self.status).grid(column=0, row=4, sticky="w", pady=(8, 0))

    def clear_form(self) -> None:
        self.selected_index = None
        for value in self.values.values():
            value.set("")
        self.values["type"].set("video")
        self.table.selection_remove(self.table.selection())

    def form_entry(self) -> dict[str, str] | None:
        entry, missing = gui_common.normalise_show_entry(
            {field: value.get() for field, value in self.values.items()}
        )
        if missing:
            self.status.set(f"Missing required fields: {', '.join(missing)}")
            return None
        assert entry is not None
        return entry

    def save_form(self) -> None:
        entry = self.form_entry()
        if entry is None:
            return
        if self.selected_index is None:
            self.entries.append(entry)
            self.selected_index = len(self.entries) - 1
        else:
            self.entries[self.selected_index] = entry
        self.refresh_table(select=self.selected_index)
        self.status.set("Entry saved.")

    def refresh_table(self, select: int | None = None) -> None:
        self.table.delete(*self.table.get_children())
        for index, entry in enumerate(self.entries):
            self.table.insert("", "end", iid=str(index), values=[entry.get(column, "") for column in self.TABLE_COLUMNS])
        if select is not None and 0 <= select < len(self.entries):
            self.table.selection_set(str(select))
            self.table.focus(str(select))
            self.table.see(str(select))

    def select_entry(self, _event=None) -> None:
        selection = self.table.selection()
        if not selection:
            return
        self.selected_index = int(selection[0])
        entry = self.entries[self.selected_index]
        for field, value in self.values.items():
            value.set(entry.get(field, ""))

    def delete_entry(self) -> None:
        if self.selected_index is None:
            return
        del self.entries[self.selected_index]
        self.clear_form()
        self.refresh_table()
        self.status.set("Entry deleted.")

    def move_entry(self, direction: int) -> None:
        if self.selected_index is None:
            return
        target = self.selected_index + direction
        if not 0 <= target < len(self.entries):
            return
        self.entries[self.selected_index], self.entries[target] = self.entries[target], self.entries[self.selected_index]
        self.selected_index = target
        self.refresh_table(select=target)

    def load_json(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("Show JSON", "*.json"), ("All files", "*")])
        if not filename:
            return
        try:
            self.entries = gui_common.load_show(Path(filename))
        except (OSError, ValueError) as exc:
            self.status.set(f"Could not load show: {exc}")
            return
        self.clear_form()
        self.refresh_table()
        self.status.set(f"Loaded {len(self.entries)} entries from {filename}.")

    def save_json(self) -> None:
        if not self.entries:
            self.status.set("Add at least one entry before saving.")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Show JSON", "*.json")])
        if not filename:
            return
        path = gui_common.save_show(Path(filename), self.entries)
        self.on_saved(path)
        self.status.set(f"Saved {len(self.entries)} entries to {path} and selected it in Config.")


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(self)
        notebook.grid(column=0, row=0, sticky="nsew")
        config = ConfigTab(notebook)
        editor = ShowEditor(notebook, on_saved=config.set_input_path)
        notebook.add(config, text="Configuration")
        notebook.add(editor, text="Show editor")


def start():
    root = tk.Tk()
    root.title("World Stage Recap Maker")
    root.minsize(820, 620)
    root.geometry("1100x820")
    app = App(master=root)
    app.mainloop()

if __name__ == "__main__":
    start()
