#!/usr/bin/env python3
"""wxPython GUI for the World Stage recap maker."""

from __future__ import annotations

from pathlib import Path
import multiprocessing as mp
from queue import Empty
from typing import Callable, cast

import wx
import wx.lib.scrolledpanel as scrolled

import common
import gui_common
import prepare
import app_config


RecapControl = wx.TextCtrl | wx.Choice | wx.CheckBox | wx.RadioBox
EntryControl = wx.TextCtrl | wx.Choice
PrepareControl = wx.TextCtrl | wx.Choice | wx.CheckBox
SettingsControl = wx.TextCtrl | wx.Choice | wx.CheckBox


class ConfigPanel(scrolled.ScrolledPanel):
    """Scrollable run configuration with native wheel/trackpad support."""

    def __init__(self, parent):
        super().__init__(parent)
        self.values: dict[str, RecapControl] = {}
        self.output_queue = mp.Queue()
        self.process: mp.Process | None = None
        self.output_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.drain_output, self.output_timer)

        root = wx.BoxSizer(wx.VERTICAL)
        self.add_section(root, "Run recap maker")
        self.add_file_row(root, "Input file", "input_file")
        self.add_section(root, "Settings")
        self.add_directory_row(root, "Temporary directory", "temp_dir", "temp")
        self.add_directory_row(root, "Output directory", "output", "output")
        self.add_checkbox(root, "Use multiprocessing", "multiprocessing", True)
        self.add_checkbox(root, "Delete temporary files", "cleanup", False)
        self.add_choice(root, "Card style", "style", list(common.colours.keys()), "70s")
        self.add_text_row(root, "Size override (WxH)", "size")
        self.add_text_row(root, "Default height", "default_height", "480")
        self.add_text_row(root, "Fade (seconds)", "fade", "0.25")
        self.add_text_row(root, "FPS", "fps", "60")
        self.add_radio(root, "Recaps", "recap_mode", [label for _value, label in gui_common.RECAP_MODES])
        self.add_checkbox(root, "Upload recaps to configured S3", "upload_recaps", True)

        self.run_button = wx.Button(self, label="Run recap maker")
        self.run_button.Bind(wx.EVT_BUTTON, self.run)
        root.Add(self.run_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        self.status = wx.StaticText(self, label="Select an input file or create one in the Show editor tab.")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(self, label="Output"), 0, wx.LEFT | wx.RIGHT, 10)
        self.output_box = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.output_box.SetMinSize(wx.Size(-1, 180))
        root.Add(self.output_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)

    def add_section(self, sizer, text: str) -> None:
        title = wx.StaticText(self, label=text)
        title.SetFont(title.GetFont().Bold().Scale(1.2))
        sizer.Add(title, 0, wx.TOP | wx.LEFT | wx.RIGHT, 12)

    def add_row(
        self,
        root: wx.Sizer,
        label: wx.StaticText,
        control: wx.Window,
        browse: Callable[[], None] | None = None,
    ) -> None:
        row = wx.BoxSizer(wx.HORIZONTAL)
        label.SetMinSize(wx.Size(175, -1))
        row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND | wx.RIGHT, 6)
        if browse:
            button = wx.Button(self, label="…", size=wx.Size(36, -1))
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

    def pick_file(self, control: wx.TextCtrl) -> None:
        with wx.FileDialog(self, "Choose file", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def pick_directory(self, control: wx.TextCtrl) -> None:
        with wx.DirDialog(self, "Choose directory") as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def text(self, name: str) -> str:
        return cast(wx.TextCtrl, self.values[name]).GetValue().strip()

    def choice(self, name: str) -> str:
        return cast(wx.Choice | wx.RadioBox, self.values[name]).GetStringSelection()

    def checked(self, name: str) -> bool:
        return cast(wx.CheckBox, self.values[name]).GetValue()

    def set_input_path(self, path: Path) -> None:
        cast(wx.TextCtrl, self.values["input_file"]).SetValue(str(path))

    def apply_persistent_settings(self, settings: dict[str, str | bool]) -> None:
        self.status.SetLabel("Persistent defaults saved; this run will use them.")

    def configuration_values(self) -> dict[str, object]:
        values: dict[str, object] = dict(app_config.recap_settings())
        values["input_file"] = self.text("input_file")
        values["temp_dir"] = self.text("temp_dir")
        values["output"] = self.text("output")
        values["multiprocessing"] = self.checked("multiprocessing")
        values["cleanup"] = self.checked("cleanup")
        values["style"] = self.choice("style")
        values["size"] = self.text("size")
        values["default_height"] = self.text("default_height")
        values["fade"] = self.text("fade")
        values["fps"] = self.text("fps")
        values["recap_mode"] = gui_common.recap_mode_from_label(self.choice("recap_mode"))
        values["upload_recaps"] = self.checked("upload_recaps")
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
        self.fields: dict[str, EntryControl] = {}

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
        if field == "type":
            return cast(wx.Choice, control).GetStringSelection().strip()
        return cast(wx.TextCtrl, control).GetValue().strip()

    def set_value(self, field: str, value: str) -> None:
        control = self.fields[field]
        if field == "type":
            cast(wx.Choice, control).SetStringSelection(value or "video")
        else:
            cast(wx.TextCtrl, control).SetValue(value)

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


class PreparePanel(scrolled.ScrolledPanel):
    """Native wx front end for the prepare.py workflow."""

    def __init__(self, parent):
        super().__init__(parent)
        self.values: dict[str, PrepareControl] = {}
        self.output_queue = mp.Queue()
        self.process: mp.Process | None = None
        self.output_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.drain_output, self.output_timer)

        root = wx.BoxSizer(wx.VERTICAL)
        self.root_sizer = root
        self.add_section(root, "Prepare media")
        self.add_choice(root, "Type", "mode", ["audio", "video"], "audio")
        cast(wx.Choice, self.values["mode"]).Bind(wx.EVT_CHOICE, self.update_mode)
        self.add_file(root, "Source media", "media_file")
        self.add_cover_extension(root)
        self.add_text(root, "Artist", "artist")
        self.add_text(root, "Title", "title")
        self.add_text(root, "Language", "language")
        self.add_directory(root, "Output directory (optional)", "output_directory")

        self.add_section(root, "Options")
        self.add_checkbox(root, "Upload to configured S3", "upload", True)
        self.subtitles_check = self.add_checkbox(root, "Include subtitles", "subtitles", False)
        self.add_checkbox(root, "Overwrite existing output files", "overwrite_existing", True)
        self.add_checkbox(root, "Clear upload cache before preparing", "clear_upload_cache", False)

        self.run_button = wx.Button(self, label="Prepare media")
        self.run_button.Bind(wx.EVT_BUTTON, self.run)
        root.Add(self.run_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        self.status = wx.StaticText(
            self, label="S3 upload settings are managed in the Settings tab."
        )
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(self, label="Output"), 0, wx.LEFT | wx.RIGHT, 10)
        self.output_box = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.output_box.SetMinSize(wx.Size(-1, 180))
        root.Add(self.output_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)
        self.update_mode()

    def add_section(self, root, text: str) -> None:
        title = wx.StaticText(self, label=text)
        title.SetFont(title.GetFont().Bold().Scale(1.2))
        root.Add(title, 0, wx.TOP | wx.LEFT | wx.RIGHT, 12)

    def add_control(
        self,
        root: wx.Sizer,
        label: str,
        control: wx.Window,
        browse: Callable[[], None] | None = None,
    ) -> wx.Sizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self, label=label)
        heading.SetMinSize(wx.Size(190, -1))
        row.Add(heading, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND | wx.RIGHT, 6)
        if browse is not None:
            button = wx.Button(self, label="…", size=wx.Size(36, -1))
            button.Bind(wx.EVT_BUTTON, lambda _event: browse())
            row.Add(button, 0)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        return row

    def add_text(self, root, label: str, name: str, value: str = "") -> None:
        control = wx.TextCtrl(self, value=value)
        self.values[name] = control
        self.add_control(root, label, control)

    def add_choice(self, root, label: str, name: str, choices: list[str], value: str) -> None:
        control = wx.Choice(self, choices=choices)
        control.SetStringSelection(value)
        self.values[name] = control
        self.add_control(root, label, control)

    def add_file(self, root, label: str, name: str) -> None:
        control = wx.TextCtrl(self)
        self.values[name] = control
        self.add_control(root, label, control, lambda: self.pick_file(control))

    def add_cover_extension(self, root) -> None:
        control = wx.TextCtrl(self, value="jpg")
        self.values["image_type"] = control
        self.cover_row = self.add_control(root, "Cover image extension", control)

    def add_directory(self, root, label: str, name: str) -> None:
        control = wx.TextCtrl(self)
        self.values[name] = control
        self.add_control(root, label, control, lambda: self.pick_directory(control))

    def add_checkbox(self, root: wx.Sizer, label: str, name: str, value: bool) -> wx.CheckBox:
        control = wx.CheckBox(self, label=label)
        control.SetValue(value)
        self.values[name] = control
        root.Add(control, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        return control

    def update_mode(self, _event=None) -> None:
        is_audio = cast(wx.Choice, self.values["mode"]).GetStringSelection() == "audio"
        self.root_sizer.Show(self.cover_row, is_audio, recursive=True)
        self.root_sizer.Show(self.subtitles_check, not is_audio, recursive=True)
        if is_audio:
            self.subtitles_check.SetValue(False)
        self.root_sizer.Layout()
        self.Layout()
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)

    def pick_file(self, control: wx.TextCtrl) -> None:
        with wx.FileDialog(self, "Choose media file", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def pick_directory(self, control: wx.TextCtrl) -> None:
        with wx.DirDialog(self, "Choose output directory") as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def request_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for name, control in self.values.items():
            if isinstance(control, wx.Choice):
                values[name] = control.GetStringSelection()
            else:
                values[name] = control.GetValue()
        return values

    def run(self, _event) -> None:
        if self.process is not None and self.process.is_alive():
            self.log("stderr", "A preparation process is already running.\n")
            return
        try:
            request = gui_common.build_prepare_request(self.request_values())
        except (KeyError, ValueError, OSError) as exc:
            self.status.SetLabel(f"Cannot start: {exc}")
            return
        self.output_box.Clear()
        self.process = mp.Process(target=gui_common.run_prepare_process, args=(request, self.output_queue))
        self.process.start()
        self.run_button.Disable()
        self.status.SetLabel("Preparing media in a background process.")
        self.log("stdout", "Started preparation process.\n")
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
            message = "completed" if self.process.exitcode == 0 else f"exited with code {self.process.exitcode}"
            self.log("stdout" if self.process.exitcode == 0 else "stderr", f"Preparation process {message}.\n")
            self.process = None
        self.output_timer.Stop()
        self.run_button.Enable()


class SettingsPanel(scrolled.ScrolledPanel):
    """Persisted application defaults shared by the recap maker and prepare.py."""

    def __init__(self, parent, on_saved):
        super().__init__(parent)
        self.on_saved = on_saved
        self.values: dict[str, SettingsControl] = {}
        settings = app_config.recap_settings()
        root = wx.BoxSizer(wx.VERTICAL)

        self.add_section(root, "Executables and downloads")
        self.add_choice(root, "SVG renderer", "card_renderer", ["inkscape", "resvg"], str(settings["card_renderer"]))
        self.add_text(root, "Inkscape", "inkscape", str(settings["inkscape"]))
        self.add_text(root, "Resvg", "resvg", str(settings["resvg"]))
        self.add_text(root, "FFmpeg", "ffmpeg", str(settings["ffmpeg"]))
        self.add_text(root, "FFprobe", "ffprobe", str(settings["ffprobe"]))
        self.add_text(root, "Browser", "browser", str(settings["browser"]))
        self.add_text(root, "PO token", "po_token", str(settings["po_token"]))

        self.add_section(root, "Cards and encoding")
        self.add_text(root, "AV1 preset", "av1_preset", str(settings["av1_preset"]))
        self.add_text(root, "AV1 CRF", "av1_crf", str(settings["av1_crf"]))
        self.add_text(root, "AV1 threads (0=auto)", "av1_threads", str(settings["av1_threads"]))
        self.add_text(root, "Opus bitrate", "opus_bitrate", str(settings["opus_bitrate"]))
        self.add_choice(root, "Audio normalization", "audio_normalization", ["none", "one-pass", "two-pass"], str(settings["audio_normalization"]))
        self.add_text(root, "Render jobs (0=auto)", "jobs", str(settings["jobs"]))

        self.add_section(root, "S3 uploads")
        try:
            s3 = prepare.load_s3_config()
            endpoint, bucket, profile = s3.endpoint_url, s3.bucket, s3.profile
        except RuntimeError:
            endpoint, bucket, profile = "", "worldstage", "r2"
        self.s3_endpoint = wx.TextCtrl(self, value=endpoint)
        self.s3_bucket = wx.TextCtrl(self, value=bucket)
        self.s3_profile = wx.TextCtrl(self, value=profile)
        self.add_control(root, "Endpoint URL", self.s3_endpoint)
        self.add_control(root, "Bucket", self.s3_bucket)
        self.add_control(root, "AWS profile", self.s3_profile)

        self.save_button = wx.Button(self, label="Save persistent settings")
        self.save_button.Bind(wx.EVT_BUTTON, self.save)
        root.Add(self.save_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 12)
        self.status = wx.StaticText(self, label=f"Configuration file: {app_config.config_path()}")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)

    def add_section(self, root, text: str) -> None:
        title = wx.StaticText(self, label=text)
        title.SetFont(title.GetFont().Bold().Scale(1.2))
        root.Add(title, 0, wx.TOP | wx.LEFT | wx.RIGHT, 12)

    def add_control(self, root: wx.Sizer, label: str, control: wx.Window) -> None:
        row = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self, label=label)
        heading.SetMinSize(wx.Size(190, -1))
        row.Add(heading, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)

    def add_text(self, root, label: str, name: str, value: str) -> None:
        control = wx.TextCtrl(self, value=value)
        self.values[name] = control
        self.add_control(root, label, control)

    def add_choice(self, root, label: str, name: str, choices: list[str], value: str) -> None:
        control = wx.Choice(self, choices=choices)
        control.SetStringSelection(value)
        self.values[name] = control
        self.add_control(root, label, control)

    def add_checkbox(self, root, label: str, name: str, value: bool) -> None:
        control = wx.CheckBox(self, label=label)
        control.SetValue(value)
        self.values[name] = control
        root.Add(control, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

    def setting_values(self) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {}
        for name, control in self.values.items():
            if isinstance(control, wx.Choice):
                values[name] = control.GetStringSelection()
            else:
                values[name] = control.GetValue()
        return values

    def save(self, _event) -> None:
        values = self.setting_values()
        try:
            path = app_config.update_recap_settings(values)
            s3_values = {
                "endpoint_url": self.s3_endpoint.GetValue().strip(),
                "bucket": self.s3_bucket.GetValue().strip(),
                "profile": self.s3_profile.GetValue().strip(),
            }
            if s3_values["endpoint_url"]:
                prepare.save_s3_config(prepare.S3Config(**s3_values))
        except (OSError, RuntimeError, ValueError) as exc:
            self.status.SetLabel(f"Could not save settings: {exc}")
            return
        self.on_saved(app_config.recap_settings())
        self.status.SetLabel(f"Saved persistent settings to {path}.")


class RecapFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="World Stage Recap Maker", size=wx.Size(1100, 820))
        self.SetMinSize(wx.Size(820, 620))
        notebook = wx.Notebook(self)
        config = ConfigPanel(notebook)
        editor = ShowEditorPanel(notebook, config.set_input_path)
        prepare_panel = PreparePanel(notebook)
        settings = SettingsPanel(notebook, config.apply_persistent_settings)
        notebook.AddPage(config, "Configuration")
        notebook.AddPage(editor, "Show editor")
        notebook.AddPage(prepare_panel, "Prepare media")
        notebook.AddPage(settings, "Settings")


def start() -> None:
    app = wx.App(False)
    frame = RecapFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    start()
