from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
import multiprocessing as mp

import common
import main

class TextRedirector:
    def __init__(self, text_widget, tag="stdout"):
        self.text_widget = text_widget
        self.tag = tag

    def write(self, message):
        self.text_widget.insert("end", message, self.tag)
        self.text_widget.see("end")

    def flush(self):
        pass

class App(tk.Frame):
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

    def run(self):
        common.OUT_HANDLE = TextRedirector(self.log_area, "stdout")
        common.ERR_HANDLE = TextRedirector(self.log_area, "stderr")

        tmpdir = Path(self.tmp_path.get())

        args = common.Args(
            csv=Path(self.csv_path.get()),
            tmpdir=tmpdir,
            browser=self.browser.get().lower() or None,
            po_token=self.po_token.get() or None,
            style=self.style.get(),
            size=common.parse_size(self.size.get()),
            output=Path(self.output_path.get()),
            fps=int(self.fps.get()),
            fade_duration=float(self.fade_duration.get()),
            multiprocessing=self.multiprocessing_var.get(),
            cleanup=self.cleanup_var.get(),
            ffmpeg=self.ffmpeg_path.get(),
            yt_dlp=self.yt_dlp_path.get(),
            inkscape=self.inkscape_path.get(),
            straight=self.straight_var.get(),
            reverse=self.reverse_var.get(),
            commondir=Path("common"),
            postcards=Path("postcards"),
            vidsdir=tmpdir / "videos",
            cardsdir=tmpdir / "cards",
            clipsdir=tmpdir / "clips",
            thumb=Path("thumb.jpg"),
            flagsdir=Path("flags"),
        )
        p = mp.Process(target=main.exec, args=(args,))
        p.start()

    def __init__(self, master):
        super().__init__(master)
        self._row = 0
        self.grid()

        ttk.Label(self, text="General settings", font=("", 18, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="CSV file").grid(column=0, row=self.row(), sticky="e")
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
        ttk.Label(self, text="Inkscape").grid(column=0, row=self.row(), sticky="e")
        self.inkscape_path = tk.StringVar(value="inkscape")
        self.inkscape_entry = ttk.Entry(self, textvariable=self.inkscape_path)
        self.inkscape_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.inkscape_path)).grid(column=2, row=self._row)
        ttk.Label(self, text="FFmpeg").grid(column=0, row=self.row(), sticky="e")
        self.ffmpeg_path = tk.StringVar(value="ffmpeg")
        self.ffmpeg_entry = ttk.Entry(self, textvariable=self.ffmpeg_path)
        self.ffmpeg_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.ffmpeg_path)).grid(column=2, row=self._row)
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
        ttk.Label(self, text="Size (WxH)").grid(column=0, row=self.row(), sticky="e")
        self.size = tk.StringVar(value="1920x1080")
        self.size_entry = ttk.Entry(self, textvariable=self.size)
        self.size_entry.grid(column=1, row=self._row, sticky="ew")

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
        ttk.Label(self, text="Straight recap").grid(column=0, row=self.row(), sticky="e")
        self.straight_var = tk.BooleanVar(value=True)
        self.straight_check = ttk.Checkbutton(self, variable=self.straight_var)
        self.straight_check.grid(column=1, row=self._row)
        ttk.Label(self, text="Reverse recap").grid(column=0, row=self.row(), sticky="e")
        self.reverse_var = tk.BooleanVar(value=True)
        self.reverse_check = ttk.Checkbutton(self, variable=self.reverse_var)
        self.reverse_check.grid(column=1, row=self._row)

        ttk.Button(self, text="Run", command=self.run).grid(column=0, row=self.row(), columnspan=3)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL)
        self.log_area = tk.Text(self, wrap=tk.WORD, height=10, yscrollcommand=scrollbar.set)
        self.log_area.grid(column=0, row=self.row(), columnspan=3, sticky="nsew")
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(self._row, weight=2)


def start():
    root = tk.Tk()
    root.title("Simple GUI")
    app = App(master=root)
    app.mainloop()

if __name__ == "__main__":
    start()