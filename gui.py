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
            size=common.parse_size(self.size.get()) if self.size.get().strip() else None,
            auto_height=int(self.auto_height.get()),
            output=Path(self.output_path.get()),
            fps=int(self.fps.get()),
            fade_duration=float(self.fade_duration.get()),
            av1_preset=int(self.av1_preset.get()),
            av1_crf=int(self.av1_crf.get()),
            av1_threads=int(self.av1_threads.get()),
            opus_bitrate=self.opus_bitrate.get(),
            audio_normalization=self.audio_normalization.get(),
            jobs=int(self.jobs.get()),
            multiprocessing=self.multiprocessing_var.get(),
            cleanup=self.cleanup_var.get(),
            ffmpeg=self.ffmpeg_path.get(),
            ffprobe=self.ffprobe_path.get(),
            yt_dlp=self.yt_dlp_path.get(),
            inkscape=self.inkscape_path.get(),
            card_renderer=self.card_renderer.get(),
            resvg=self.resvg_path.get(),
            only_straight=self.straight_var.get(),
            only_reverse=self.reverse_var.get(),
            vidsdir=tmpdir / "sources",
            cardsdir=tmpdir / "cards",
            clipsdir=tmpdir / "clips",
        )
        p = mp.Process(target=main.exec, args=(args,))
        p.start()

    def __init__(self, master):
        super().__init__(master)
        self._row = 0
        self.grid()

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
        ttk.Label(self, text="Inkscape").grid(column=0, row=self.row(), sticky="e")
        self.inkscape_path = tk.StringVar(value="inkscape")
        self.inkscape_entry = ttk.Entry(self, textvariable=self.inkscape_path)
        self.inkscape_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.inkscape_path)).grid(column=2, row=self._row)
        ttk.Label(self, text="Card renderer").grid(column=0, row=self.row(), sticky="e")
        self.card_renderer = tk.StringVar(value="inkscape")
        self.card_renderer_entry = ttk.Combobox(self, textvariable=self.card_renderer, values=["inkscape", "resvg"])
        self.card_renderer_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Label(self, text="Resvg").grid(column=0, row=self.row(), sticky="e")
        self.resvg_path = tk.StringVar(value="rsvg-convert")
        self.resvg_entry = ttk.Entry(self, textvariable=self.resvg_path)
        self.resvg_entry.grid(column=1, row=self._row, sticky="ew")
        ttk.Button(self, text="...", command=lambda: self.pick_file(self.resvg_path)).grid(column=2, row=self._row)
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
        ttk.Label(self, text="The next two are mutually exclusive", font=("", 12, "bold")).grid(column=0, row=self.row(), columnspan=3)
        ttk.Label(self, text="Only straight recap").grid(column=0, row=self.row(), sticky="e")
        self.straight_var = tk.BooleanVar(value=False)
        self.straight_check = ttk.Checkbutton(self, variable=self.straight_var)
        self.straight_check.grid(column=1, row=self._row)
        ttk.Label(self, text="Only reverse recap").grid(column=0, row=self.row(), sticky="e")
        self.reverse_var = tk.BooleanVar(value=False)
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
