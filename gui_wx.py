#!/usr/bin/env python3
"""wxPython GUI for the World Stage recap maker.

The Tk GUI remains available in ``gui.py``.  This version uses native wx
scrolling and controls, which behave more naturally with macOS trackpads.
"""

# pyright: reportMissingImports=false

from __future__ import annotations

from pathlib import Path
import multiprocessing as mp
from queue import Empty

try:
    import wx
    import wx.lib.scrolledpanel as scrolled
except ImportError as exc:  # pragma: no cover - depends on optional GUI package
    raise SystemExit("wxPython is required for gui_wx.py. Install it with: pip install wxPython") from exc

import common
import gui_common


class ConfigPanel(scrolled.ScrolledPanel):
    """Scrollable run configuration with native wheel/trackpad support."""

    def __init__(self, parent):
        super().__init__(parent)
        self.values: dict[str, wx.Window] = {}
        self.renderer_paths = {"inkscape": "inkscape", "resvg": "rsvg-convert"}
        self.output_queue = mp.Queue()
        self.process: mp.Process | None = None
        self.output_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.drain_output, self.output_timer)

        root = wx.BoxSizer(wx.VERTICAL)
        self.add_section(root, "General settings")
        self.add_file_row(root, "Input file", "input_file")
        self.add_directory_row(root, "Temp directory", "temp_dir", "temp")
        self.add_checkbox(root, "Multiprocessing", "multiprocessing", True)
        self.add_checkbox(root, "Delete temporary files", "cleanup", False)

        self.add_section(root, "Executables")
        self.add_choice(root, "SVG renderer", "card_renderer", ["inkscape", "resvg"], "inkscape", self.renderer_changed)
        self.renderer_label = wx.StaticText(self, label="Inkscape")
        self.renderer_path = wx.TextCtrl(self, value="inkscape")
        self.add_row(root, self.renderer_label, self.renderer_path, self.pick_renderer_path)
        self.add_file_row(root, "FFmpeg", "ffmpeg", "ffmpeg")
        self.add_file_row(root, "FFprobe", "ffprobe", "ffprobe")
        self.add_file_row(root, "yt-dlp", "yt_dlp", "yt-dlp")

        self.add_section(root, "Download settings")
        self.add_text_row(root, "Browser", "browser")
        self.add_text_row(root, "PO token", "po_token")

        self.add_section(root, "Card settings")
        self.add_choice(root, "Style", "style", list(common.colours.keys()), "70s")
        self.add_text_row(root, "Size override (WxH)", "size")
        self.add_text_row(root, "Automatic height", "auto_height", "1080")

        self.add_section(root, "Recap settings")
        self.add_directory_row(root, "Output directory", "output", "output")
        self.add_text_row(root, "Fade (seconds)", "fade", "0.25")
        self.add_text_row(root, "FPS", "fps", "60")
        self.add_text_row(root, "AV1 preset", "av1_preset", "8")
        self.add_text_row(root, "AV1 CRF", "av1_crf", "30")
        self.add_text_row(root, "AV1 threads (0=auto)", "av1_threads", "0")
        self.add_text_row(root, "Opus bitrate", "opus_bitrate", "160k")
        self.add_choice(root, "Audio normalization", "audio_normalization", ["none", "one-pass", "two-pass"], "two-pass")
        self.add_text_row(root, "Render jobs (0=auto)", "jobs", "0")
        self.add_radio(root, "Recaps", "recap_mode", [label for _value, label in gui_common.RECAP_MODES])

        self.run_button = wx.Button(self, label="Run recap maker")
        self.run_button.Bind(wx.EVT_BUTTON, self.run)
        root.Add(self.run_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        self.status = wx.StaticText(self, label="Select an input file or create one in the Show editor tab.")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(self, label="Output"), 0, wx.LEFT | wx.RIGHT, 10)
        self.output_box = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.output_box.SetMinSize((-1, 180))
        root.Add(self.output_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)

    def add_section(self, sizer, text: str) -> None:
        title = wx.StaticText(self, label=text)
        title.SetFont(title.GetFont().Bold().Scale(1.2))
        sizer.Add(title, 0, wx.TOP | wx.LEFT | wx.RIGHT, 12)

    def add_row(self, root, label, control, browse=None) -> None:
        row = wx.BoxSizer(wx.HORIZONTAL)
        label.SetMinSize((175, -1))
        row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND | wx.RIGHT, 6)
        if browse:
            button = wx.Button(self, label="…", size=(36, -1))
            button.Bind(wx.EVT_BUTTON, lambda _event: browse())
            row.Add(button, 0)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

    def add_text_row(self, root, label: str, name: str, value: str = "") -> None:
        control = wx.TextCtrl(self, value=value)
        self.values[name] = control
        self.add_row(root, wx.StaticText(self, label=label), control)

    def add_file_row(self, root, label: str, name: str, value: str = "") -> None:
        control = wx.TextCtrl(self, value=value)
        self.values[name] = control
        self.add_row(root, wx.StaticText(self, label=label), control, lambda: self.pick_file(control))

    def add_directory_row(self, root, label: str, name: str, value: str = "") -> None:
        control = wx.TextCtrl(self, value=value)
        self.values[name] = control
        self.add_row(root, wx.StaticText(self, label=label), control, lambda: self.pick_directory(control))

    def add_checkbox(self, root, label: str, name: str, value: bool) -> None:
        control = wx.CheckBox(self, label=label)
        control.SetValue(value)
        self.values[name] = control
        root.Add(control, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

    def add_radio(self, root, label: str, name: str, choices: list[str]) -> None:
        control = wx.RadioBox(self, label=label, choices=choices, majorDimension=1, style=wx.RA_SPECIFY_ROWS)
        control.SetSelection(0)
        self.values[name] = control
        root.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)

    def add_choice(self, root, label: str, name: str, choices: list[str], value: str, handler=None) -> None:
        control = wx.Choice(self, choices=choices)
        control.SetStringSelection(value)
        self.values[name] = control
        if handler:
            control.Bind(wx.EVT_CHOICE, handler)
        self.add_row(root, wx.StaticText(self, label=label), control)

    def pick_file(self, control) -> None:
        with wx.FileDialog(self, "Choose file", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def pick_directory(self, control) -> None:
        with wx.DirDialog(self, "Choose directory") as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def renderer_changed(self, _event) -> None:
        selected = self.choice("card_renderer")
        self.renderer_paths["inkscape" if self.renderer_label.GetLabel() == "Inkscape" else "resvg"] = self.renderer_path.GetValue()
        self.renderer_label.SetLabel("Resvg" if selected == "resvg" else "Inkscape")
        self.renderer_path.SetValue(self.renderer_paths[selected])
        self.Layout()

    def pick_renderer_path(self) -> None:
        self.pick_file(self.renderer_path)
        self.renderer_paths[self.choice("card_renderer")] = self.renderer_path.GetValue()

    def text(self, name: str) -> str:
        return self.values[name].GetValue().strip()

    def choice(self, name: str) -> str:
        return self.values[name].GetStringSelection()

    def checked(self, name: str) -> bool:
        return self.values[name].GetValue()

    def set_input_path(self, path: Path) -> None:
        self.values["input_file"].SetValue(str(path))

    def configuration_values(self) -> dict[str, object]:
        values: dict[str, object] = {
            "input_file": self.text("input_file"), "temp_dir": self.text("temp_dir"),
            "browser": self.text("browser"), "po_token": self.text("po_token"),
            "style": self.choice("style"), "size": self.text("size"),
            "auto_height": self.text("auto_height"), "output": self.text("output"),
            "fps": self.text("fps"), "fade": self.text("fade"),
            "av1_preset": self.text("av1_preset"), "av1_crf": self.text("av1_crf"),
            "av1_threads": self.text("av1_threads"), "opus_bitrate": self.text("opus_bitrate"),
            "audio_normalization": self.choice("audio_normalization"), "jobs": self.text("jobs"),
            "multiprocessing": self.checked("multiprocessing"), "cleanup": self.checked("cleanup"),
            "ffmpeg": self.text("ffmpeg"), "ffprobe": self.text("ffprobe"),
            "yt_dlp": self.text("yt_dlp"), "inkscape": self.renderer_paths["inkscape"],
            "card_renderer": self.choice("card_renderer"), "resvg": self.renderer_paths["resvg"],
            "recap_mode": gui_common.recap_mode_from_label(self.choice("recap_mode")),
        }
        self.renderer_paths[self.choice("card_renderer")] = self.renderer_path.GetValue().strip()
        values["inkscape"] = self.renderer_paths["inkscape"]
        values["resvg"] = self.renderer_paths["resvg"]
        return values

    def run(self, _event) -> None:
        if self.process is not None and self.process.is_alive():
            self.log("stderr", "A recap-maker process is already running.\n")
            return
        try:
            args = gui_common.build_args(self.configuration_values())
        except (KeyError, ValueError, OSError) as exc:
            self.status.SetLabel(f"Cannot start: {exc}")
            return
        self.output_box.Clear()
        self.process = mp.Process(target=gui_common.run_recap_process, args=(args, self.output_queue))
        self.process.start()
        self.run_button.Disable()
        self.status.SetLabel("Recap maker started in a background process.")
        self.log("stdout", "Started recap-maker process.\n")
        self.output_timer.Start(50)

    def log(self, tag: str, message: str) -> None:
        prefix = "[error] " if tag == "stderr" else ""
        self.output_box.AppendText(prefix + message)
        self.output_box.ShowPosition(self.output_box.GetLastPosition())

    def drain_output(self, _event) -> None:
        while True:
            try:
                tag, message = self.output_queue.get_nowait()
            except Empty:
                break
            self.log(tag, message)

        if self.process is not None and self.process.is_alive():
            return
        if self.process is not None:
            self.process.join()
            status = "completed" if self.process.exitcode == 0 else f"exited with code {self.process.exitcode}"
            self.log("stdout" if self.process.exitcode == 0 else "stderr", f"Recap-maker process {status}.\n")
            self.process = None
        self.output_timer.Stop()
        self.run_button.Enable()


class ShowEditorPanel(wx.Panel):
    FIELDS = gui_common.SHOW_FIELDS
    TABLE_COLUMNS = gui_common.SHOW_TABLE_COLUMNS

    def __init__(self, parent, on_saved):
        super().__init__(parent)
        self.on_saved = on_saved
        self.entries: list[dict[str, str]] = []
        self.selected_index: int | None = None
        self.fields: dict[str, wx.Window] = {}

        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label="Show editor")
        title.SetFont(title.GetFont().Bold().Scale(1.3))
        root.Add(title, 0, wx.ALL, 8)

        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, column in enumerate(self.TABLE_COLUMNS):
            self.table.InsertColumn(index, column.replace("_", " ").title())
            self.table.SetColumnWidth(index, 110)
        self.table.SetColumnWidth(3, 180)
        self.table.SetColumnWidth(4, 200)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.select_entry)
        root.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        toolbar = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in [
            ("New", self.clear_form), ("Add / update", self.save_form), ("Delete", self.delete_entry),
            ("Move up", lambda _event: self.move_entry(-1)), ("Move down", lambda _event: self.move_entry(1)),
            ("Load JSON", self.load_json), ("Save JSON", self.save_json),
        ]:
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            toolbar.Add(button, 0, wx.RIGHT | wx.BOTTOM, 6)
        root.Add(toolbar, 0, wx.LEFT | wx.RIGHT, 8)

        form_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Selected entry")
        form = wx.FlexGridSizer(cols=4, hgap=8, vgap=6)
        form.AddGrowableCol(1, 1)
        form.AddGrowableCol(3, 1)
        for index, (field, label) in enumerate(self.FIELDS):
            form.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
            if field == "type":
                control = wx.Choice(self, choices=["video", "audio"])
                control.SetStringSelection("video")
            else:
                control = wx.TextCtrl(self)
            self.fields[field] = control
            form.Add(control, 1, wx.EXPAND)
        form_box.Add(form, 1, wx.EXPAND | wx.ALL, 8)
        root.Add(form_box, 0, wx.EXPAND | wx.ALL, 8)

        self.status = wx.StaticText(self, label="Create entries, then save a JSON show file.")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(root)

    def value(self, field: str) -> str:
        control = self.fields[field]
        return control.GetStringSelection().strip() if field == "type" else control.GetValue().strip()

    def set_value(self, field: str, value: str) -> None:
        control = self.fields[field]
        if field == "type":
            control.SetStringSelection(value or "video")
        else:
            control.SetValue(value)

    def clear_form(self, _event=None) -> None:
        self.selected_index = None
        for field, _label in self.FIELDS:
            self.set_value(field, "video" if field == "type" else "")
        self.table.SetItemState(-1, 0, wx.LIST_STATE_SELECTED)

    def form_entry(self) -> dict[str, str] | None:
        entry, missing = gui_common.normalise_show_entry(
            {field: self.value(field) for field, _label in self.FIELDS}
        )
        if missing:
            self.status.SetLabel(f"Missing required fields: {', '.join(missing)}")
            return None
        assert entry is not None
        return entry

    def save_form(self, _event) -> None:
        entry = self.form_entry()
        if entry is None:
            return
        if self.selected_index is None:
            self.entries.append(entry)
            self.selected_index = len(self.entries) - 1
        else:
            self.entries[self.selected_index] = entry
        self.refresh_table(self.selected_index)
        self.status.SetLabel("Entry saved.")

    def refresh_table(self, selected: int | None = None) -> None:
        self.table.DeleteAllItems()
        for index, entry in enumerate(self.entries):
            row = self.table.InsertItem(index, entry.get("ro", ""))
            for column, field in enumerate(self.TABLE_COLUMNS[1:], start=1):
                self.table.SetItem(row, column, entry.get(field, ""))
        if selected is not None and 0 <= selected < len(self.entries):
            self.table.SetItemState(selected, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            self.table.EnsureVisible(selected)

    def select_entry(self, event) -> None:
        index = int(event.GetIndex())
        if not 0 <= index < len(self.entries):
            return
        self.selected_index = index
        entry = self.entries[index]
        for field, _label in self.FIELDS:
            self.set_value(field, entry.get(field, ""))

    def delete_entry(self, _event) -> None:
        if self.selected_index is None:
            return
        del self.entries[self.selected_index]
        self.clear_form()
        self.refresh_table()
        self.status.SetLabel("Entry deleted.")

    def move_entry(self, direction: int) -> None:
        if self.selected_index is None:
            return
        target = self.selected_index + direction
        if not 0 <= target < len(self.entries):
            return
        self.entries[self.selected_index], self.entries[target] = self.entries[target], self.entries[self.selected_index]
        self.selected_index = target
        self.refresh_table(target)

    def load_json(self, _event) -> None:
        with wx.FileDialog(self, "Load show JSON", wildcard="JSON files (*.json)|*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        try:
            self.entries = gui_common.load_show(path)
        except (OSError, ValueError) as exc:
            self.status.SetLabel(f"Could not load show: {exc}")
            return
        self.clear_form()
        self.refresh_table()
        self.status.SetLabel(f"Loaded {len(self.entries)} entries from {path}.")

    def save_json(self, _event) -> None:
        if not self.entries:
            self.status.SetLabel("Add at least one entry before saving.")
            return
        with wx.FileDialog(self, "Save show JSON", wildcard="JSON files (*.json)|*.json", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        path = gui_common.save_show(path, self.entries)
        self.on_saved(path)
        self.status.SetLabel(f"Saved {len(self.entries)} entries and selected it in Configuration.")


class RecapFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="World Stage Recap Maker", size=(1100, 820))
        self.SetMinSize((820, 620))
        notebook = wx.Notebook(self)
        config = ConfigPanel(notebook)
        editor = ShowEditorPanel(notebook, config.set_input_path)
        notebook.AddPage(config, "Configuration")
        notebook.AddPage(editor, "Show editor")


def start() -> None:
    app = wx.App(False)
    frame = RecapFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    start()
