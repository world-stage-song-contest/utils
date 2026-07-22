#!/usr/bin/env python3
"""wxPython GUI for the World Stage recap maker."""

from __future__ import annotations

from pathlib import Path
import multiprocessing as mp
from queue import Empty
from typing import Callable, MutableMapping, cast

import wx
import wx.lib.scrolledpanel as scrolled

import common
import gui_common
import prepare
import app_config
import recap_api


EntryControl = wx.TextCtrl | wx.Choice


class FormBuilder:
    """Reusable labelled controls and pickers for the wx configuration tabs."""

    def __init__(self, panel: wx.Window, values: MutableMapping[str, wx.Window], label_width: int):
        self.panel = panel
        self.values = values
        self.label_width = label_width

    def section(self, root: wx.Sizer, text: str) -> None:
        title = wx.StaticText(self.panel, label=text)
        title.SetFont(title.GetFont().Bold().Scale(1.2))
        root.Add(title, 0, wx.TOP | wx.LEFT | wx.RIGHT, 12)

    def control(
        self,
        root: wx.Sizer,
        label: str,
        control: wx.Window,
        browse: Callable[[], None] | None = None,
    ) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self.panel, label=label)
        heading.SetMinSize(wx.Size(self.label_width, -1))
        row.Add(heading, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND | wx.RIGHT, 6)
        if browse is not None:
            button = wx.Button(self.panel, label="…", size=wx.Size(36, -1))
            button.Bind(wx.EVT_BUTTON, lambda _event: browse())
            row.Add(button, 0)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
        return row

    def text(
        self, root: wx.Sizer, label: str, name: str, value: str = "", *, style: int = 0,
    ) -> wx.BoxSizer:
        control = wx.TextCtrl(self.panel, value=value, style=style)
        self.values[name] = control
        return self.control(root, label, control)

    def choice(
        self,
        root: wx.Sizer,
        label: str,
        name: str,
        choices: list[str],
        value: str,
        handler: Callable | None = None,
    ) -> wx.BoxSizer:
        control = wx.Choice(self.panel, choices=choices)
        control.SetStringSelection(value)
        self.values[name] = control
        if handler is not None:
            control.Bind(wx.EVT_CHOICE, handler)
        return self.control(root, label, control)

    def file(
        self,
        root: wx.Sizer,
        label: str,
        name: str,
        *,
        dialog_title: str,
        wildcard: str = "All files (*.*)|*.*",
    ) -> wx.BoxSizer:
        control = wx.TextCtrl(self.panel)
        self.values[name] = control
        return self.control(root, label, control, lambda: self.pick_file(control, dialog_title, wildcard))

    def directory(self, root: wx.Sizer, label: str, name: str, value: str = "", *, dialog_title: str) -> wx.BoxSizer:
        control = wx.TextCtrl(self.panel, value=value)
        self.values[name] = control
        return self.control(root, label, control, lambda: self.pick_directory(control, dialog_title))

    def checkbox(self, root: wx.Sizer, label: str, name: str, value: bool) -> wx.CheckBox:
        control = wx.CheckBox(self.panel, label=label)
        control.SetValue(value)
        self.values[name] = control
        root.Add(control, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        return control

    def radio(self, root: wx.Sizer, label: str, name: str, choices: list[str]) -> wx.RadioBox:
        control = wx.RadioBox(self.panel, label=label, choices=choices, majorDimension=1, style=wx.RA_SPECIFY_ROWS)
        control.SetSelection(0)
        self.values[name] = control
        root.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        return control

    def pick_file(self, control: wx.TextCtrl, title: str, wildcard: str) -> None:
        with wx.FileDialog(self.panel, title, wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def pick_directory(self, control: wx.TextCtrl, title: str) -> None:
        with wx.DirDialog(self.panel, title) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                control.SetValue(dialog.GetPath())

    def values_as_dict(self) -> dict[str, object]:
        return {
            name: control.GetStringSelection()
            if isinstance(control, (wx.Choice, wx.RadioBox))
            else cast(wx.TextCtrl | wx.CheckBox, control).GetValue()
            for name, control in self.values.items()
        }

    @staticmethod
    def refresh_s3_upload(control: wx.CheckBox, tooltip: str) -> None:
        available = prepare.s3_configured()
        control.SetValue(available)
        control.Enable(available)
        if not available:
            control.SetToolTip(tooltip)


class BackgroundProcessOutput:
    """Run a multiprocessing job and stream its output into one text control."""

    def __init__(
        self,
        panel: wx.Window,
        output_box: wx.TextCtrl,
        run_button: wx.Button,
        status: wx.StaticText,
        process_name: str,
    ):
        self.output_box = output_box
        self.run_button = run_button
        self.status = status
        self.process_name = process_name
        self.output_queue = mp.Queue()
        self.process: mp.Process | None = None
        self.output_timer = wx.Timer(panel)
        panel.Bind(wx.EVT_TIMER, self.drain_output, self.output_timer)

    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def launch(
        self,
        target: Callable,
        request: object,
        *,
        started_status: str,
        started_message: str,
    ) -> None:
        self.output_box.Clear()
        self.process = mp.Process(target=target, args=(request, self.output_queue))
        self.process.start()
        self.run_button.Disable()
        self.status.SetLabel(started_status)
        self.log("stdout", started_message)
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
            outcome = "completed" if self.process.exitcode == 0 else f"exited with code {self.process.exitcode}"
            self.log(
                "stdout" if self.process.exitcode == 0 else "stderr",
                f"{self.process_name} {outcome}.\n",
            )
            self.process = None
        self.output_timer.Stop()
        self.run_button.Enable()


class ApiInputControls:
    """Shared File/World Stage API input controls for media-processing tabs."""

    values: dict[str, wx.Window]
    root_sizer: wx.BoxSizer
    status: wx.StaticText

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def add_api_input_controls(
        self,
        root: wx.Sizer,
        *,
        input_name: str,
        add_file: Callable[[wx.Sizer, str, str], wx.BoxSizer],
        add_text: Callable[[wx.Sizer, str, str], wx.BoxSizer],
        add_choice: Callable[..., wx.BoxSizer],
    ) -> None:
        """Add one consistent API selector while retaining each panel's layout."""
        panel = cast(scrolled.ScrolledPanel, self)
        self.api_input_name = input_name
        add_choice(root, "Input source", "input_source", ["File", "World Stage API"], "File", self.update_input_source)
        self.file_input_row = add_file(root, "Input file", input_name)
        self.api_type_row = add_choice(root, "API type", "api_type", sorted(recap_api.API_TYPES), "year")
        self.api_shows_row = add_text(root, "API shows", "api_shows")
        self.api_shows_hint = wx.StaticText(panel, label="Separate multiple show values with semicolons")
        root.Add(self.api_shows_hint, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.ALIGN_CENTER_HORIZONTAL, 4)
        self.api_specials_row = add_choice(root, "API specials", "api_specials", sorted(recap_api.SPECIALS), "false")
        self.fetch_api_button = wx.Button(panel, label="Fetch API JSON")
        self.fetch_api_button.Bind(wx.EVT_BUTTON, self.fetch_api)
        root.Add(self.fetch_api_button, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)

    def fetch_api(self, _event) -> None:
        query_type = cast(wx.Choice, self.values["api_type"]).GetStringSelection()
        if not query_type:
            raise ValueError("Choose an API type before fetching")
        shows = tuple(
            value.strip()
            for value in cast(wx.TextCtrl, self.values["api_shows"]).GetValue().split(";")
            if value.strip()
        )
        specials = cast(wx.Choice, self.values["api_specials"]).GetStringSelection()
        path = recap_api.fetch_to_cache(recap_api.ApiQuery(query_type, shows, specials))
        cast(wx.TextCtrl, self.values[self.api_input_name]).SetValue(str(path))
        self.status.SetLabel(f"Fetched API JSON to {path}.")

    def update_input_source(self, _event=None) -> None:
        api = cast(wx.Choice, self.values["input_source"]).GetStringSelection() == "World Stage API"
        self.root_sizer.Show(self.file_input_row, not api, recursive=True)
        for item in (
            self.api_type_row, self.api_shows_row, self.api_shows_hint,
            self.api_specials_row, self.fetch_api_button,
        ):
            self.root_sizer.Show(item, api, recursive=True)
        self.root_sizer.Layout()
        panel = cast(scrolled.ScrolledPanel, self)
        panel.Layout()
        panel.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)


class ConfigPanel(ApiInputControls, scrolled.ScrolledPanel):
    """Scrollable run configuration with native wheel/trackpad support."""

    def __init__(self, parent):
        super().__init__(parent)
        self.values: dict[str, wx.Window] = {}
        self.form = FormBuilder(self, self.values, 175)

        root = wx.BoxSizer(wx.VERTICAL)
        self.root_sizer = root
        self.form.section(root, "Run recap maker")
        self.add_api_input_controls(
            root, input_name="input_file", add_file=lambda *_args: self.form.file(
                *_args, dialog_title="Choose file"
            ), add_text=self.form.text, add_choice=self.form.choice,
        )
        self.form.section(root, "Settings")
        self.form.directory(root, "Temporary directory", "temp_dir", "temp", dialog_title="Choose directory")
        self.form.directory(root, "Output directory", "output", "output", dialog_title="Choose directory")
        self.form.checkbox(root, "Use multiprocessing", "multiprocessing", True)
        self.form.checkbox(root, "Delete temporary files", "cleanup", False)
        self.form.choice(root, "Card style", "style", list(common.colours.keys()), "70s")
        self.form.text(root, "Size override (WxH)", "size")
        self.form.text(root, "Default height", "default_height", "480")
        self.form.text(root, "Fade (seconds)", "fade", "0.25")
        self.form.text(root, "FPS", "fps", "60")
        self.form.text(
            root, "Concurrent recap renders (0=auto)", "jobs",
            str(app_config.recap_settings()["jobs"]),
        )
        self.form.radio(root, "Recaps", "recap_mode", [label for _value, label in gui_common.RECAP_MODES])
        self.form.checkbox(root, "Upload to configured S3", "upload_recaps", True)
        self.refresh_upload_availability()

        self.run_button = wx.Button(self, label="Run recap maker")
        self.run_button.Bind(wx.EVT_BUTTON, self.run)
        root.Add(self.run_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        self.status = wx.StaticText(self, label="Select an input file or create one in the Show editor tab.")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(self, label="Output"), 0, wx.LEFT | wx.RIGHT, 10)
        self.output_box = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.output_box.SetMinSize(wx.Size(-1, 180))
        root.Add(self.output_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.process_output = BackgroundProcessOutput(
            self, self.output_box, self.run_button, self.status, "Recap-maker process",
        )

        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)
        self.update_input_source()

    def refresh_upload_availability(self) -> None:
        control = cast(wx.CheckBox, self.values["upload_recaps"])
        self.form.refresh_s3_upload(control, "Configure S3 in Settings to enable recap uploads.")

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
        values["jobs"] = self.text("jobs")
        values["recap_mode"] = gui_common.recap_mode_from_label(self.choice("recap_mode"))
        values["upload_recaps"] = self.checked("upload_recaps")
        return values

    def run(self, _event) -> None:
        if self.process_output.is_running():
            self.process_output.log("stderr", "A recap-maker process is already running.\n")
            return
        try:
            args = gui_common.build_args(self.configuration_values())
        except (KeyError, ValueError, OSError) as exc:
            self.status.SetLabel(f"Cannot start: {exc}")
            raise
        self.process_output.launch(
            gui_common.run_gui_process, gui_common.GuiWorkerJob("recap", args),
            started_status="Recap maker started in a background process.",
            started_message="Started recap-maker process.\n",
        )


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
            raise
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
        self.values: dict[str, wx.Window] = {}
        self.form = FormBuilder(self, self.values, 190)

        root = wx.BoxSizer(wx.VERTICAL)
        self.root_sizer = root
        self.form.section(root, "Prepare media")
        self.form.choice(root, "Type", "mode", ["audio", "video"], "audio")
        cast(wx.Choice, self.values["mode"]).Bind(wx.EVT_CHOICE, self.update_mode)
        self.form.file(root, "Source media", "media_file", dialog_title="Choose media file")
        self.add_cover_extension(root)
        self.form.text(root, "Artist", "artist")
        self.form.text(root, "Title", "title")
        self.form.text(root, "Language", "language")
        self.form.directory(root, "Output directory (optional)", "output_directory", dialog_title="Choose output directory")

        self.form.section(root, "Options")
        self.upload_check = self.form.checkbox(root, "Upload to configured S3", "upload", True)
        self.subtitles_check = self.form.checkbox(root, "Include subtitles", "subtitles", False)
        self.form.checkbox(root, "Overwrite existing output files", "overwrite_existing", True)
        self.form.checkbox(root, "Clear upload cache before preparing", "clear_upload_cache", False)

        self.run_button = wx.Button(self, label="Prepare media")
        self.run_button.Bind(wx.EVT_BUTTON, self.run)
        root.Add(self.run_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        self.status = wx.StaticText(
            self, label="S3 upload settings are managed in the Settings tab."
        )
        self.refresh_upload_availability()
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(self, label="Output"), 0, wx.LEFT | wx.RIGHT, 10)
        self.output_box = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.output_box.SetMinSize(wx.Size(-1, 180))
        root.Add(self.output_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.process_output = BackgroundProcessOutput(
            self, self.output_box, self.run_button, self.status, "Preparation process",
        )
        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)
        self.update_mode()

    def add_cover_extension(self, root) -> None:
        control = wx.TextCtrl(self, value="jpg")
        self.values["image_type"] = control
        self.cover_row = self.form.control(root, "Cover image extension", control)

    def refresh_upload_availability(self) -> None:
        self.form.refresh_s3_upload(self.upload_check, "Configure S3 in Settings to enable uploads.")

    def update_mode(self, _event=None) -> None:
        is_audio = cast(wx.Choice, self.values["mode"]).GetStringSelection() == "audio"
        self.root_sizer.Show(self.cover_row, is_audio, recursive=True)
        self.root_sizer.Show(self.subtitles_check, not is_audio, recursive=True)
        if is_audio:
            self.subtitles_check.SetValue(False)
        self.root_sizer.Layout()
        self.Layout()
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)

    def request_values(self) -> dict[str, object]:
        return self.form.values_as_dict()

    def run(self, _event) -> None:
        if self.process_output.is_running():
            self.process_output.log("stderr", "A preparation process is already running.\n")
            return
        try:
            request = gui_common.build_prepare_request(self.request_values())
        except (KeyError, ValueError, OSError) as exc:
            self.status.SetLabel(f"Cannot start: {exc}")
            raise
        self.process_output.launch(
            gui_common.run_gui_process, gui_common.GuiWorkerJob("prepare", request),
            started_status="Preparing media in a background process.",
            started_message="Started preparation process.\n",
        )


class BatchDownloadPanel(ApiInputControls, scrolled.ScrolledPanel):
    """Download and tag all available video rows in a show file."""

    def __init__(self, parent):
        super().__init__(parent)
        self.values: dict[str, wx.Window] = {}
        self.form = FormBuilder(self, self.values, 190)

        root = wx.BoxSizer(wx.VERTICAL)
        self.root_sizer = root
        self.form.section(root, "Batch download")
        self.add_api_input_controls(
            root, input_name="input", add_file=lambda *_args: self.form.file(
                *_args, dialog_title="Choose show file",
                wildcard="Show files (*.json;*.csv)|*.json;*.csv|All files (*.*)|*.*",
            ), add_text=self.form.text, add_choice=self.form.choice,
        )
        self.form.directory(root, "Output directory", "output_directory", "output", dialog_title="Choose directory")
        self.form.directory(root, "Temporary directory (optional)", "temporary_directory", dialog_title="Choose directory")
        self.form.text(root, "Concurrent downloads (0=auto)", "jobs", "0")
        self.form.text(root, "Target video height", "target_height", "576")

        self.form.section(root, "Options")
        self.upload_check = self.form.checkbox(root, "Upload to configured S3", "upload", True)
        self.song_links_check = self.form.checkbox(root, "Update World Stage media links after upload", "update_song_links", True)
        self.upload_check.Bind(wx.EVT_CHECKBOX, self.update_song_links_availability)
        self.form.checkbox(root, "Overwrite existing output files", "overwrite", False)
        self.form.checkbox(root, "Dry run (do not download or write files)", "dry_run", False)

        self.run_button = wx.Button(self, label="Download and tag videos")
        self.run_button.Bind(wx.EVT_BUTTON, self.run)
        root.Add(self.run_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        self.status = wx.StaticText(self, label="Choose a show file to start a batch download.")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(self, label="Output"), 0, wx.LEFT | wx.RIGHT, 10)
        self.output_box = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        self.output_box.SetMinSize(wx.Size(-1, 180))
        root.Add(self.output_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.process_output = BackgroundProcessOutput(
            self, self.output_box, self.run_button, self.status, "Batch download",
        )
        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)
        self.refresh_upload_availability()
        self.update_input_source()

    def refresh_upload_availability(self) -> None:
        self.form.refresh_s3_upload(self.upload_check, "Configure S3 in Settings to enable uploads.")
        token = str(app_config.recap_settings()["song_api_token"]).strip()
        available = self.upload_check.GetValue() and bool(token)
        self.song_links_check.SetValue(available)
        self.song_links_check.Enable(available)
        if not available:
            self.song_links_check.SetToolTip(
                "Enable S3 uploads and configure a World Stage song API token in Settings.",
            )

    def update_song_links_availability(self, _event=None) -> None:
        token = str(app_config.recap_settings()["song_api_token"]).strip()
        available = self.upload_check.GetValue() and bool(token)
        if not available:
            self.song_links_check.SetValue(False)
        self.song_links_check.Enable(available)

    def request_values(self) -> dict[str, object]:
        return self.form.values_as_dict()

    def run(self, _event) -> None:
        if self.process_output.is_running():
            self.process_output.log("stderr", "A batch-download process is already running.\n")
            return
        try:
            request = gui_common.build_batch_download_request(self.request_values())
        except (KeyError, ValueError, OSError) as exc:
            self.status.SetLabel(f"Cannot start: {exc}")
            raise
        self.process_output.launch(
            gui_common.run_gui_process, gui_common.GuiWorkerJob("batch", request),
            started_status="Batch download started in a background process.",
            started_message="Started batch-download process.\n",
        )


class SettingsPanel(scrolled.ScrolledPanel):
    """Persisted application defaults shared by the recap maker and prepare.py."""

    def __init__(self, parent, on_saved):
        super().__init__(parent)
        self.on_saved = on_saved
        self.values: dict[str, wx.Window] = {}
        self.form = FormBuilder(self, self.values, 190)
        settings = app_config.recap_settings()
        root = wx.BoxSizer(wx.VERTICAL)
        self.root_sizer = root

        self.form.section(root, "Executables and downloads")
        self.form.choice(root, "SVG renderer", "card_renderer", ["inkscape", "resvg"], str(settings["card_renderer"]))
        self.form.text(root, "Inkscape", "inkscape", str(settings["inkscape"]))
        self.form.text(root, "Resvg", "resvg", str(settings["resvg"]))
        self.form.text(root, "FFmpeg", "ffmpeg", str(settings["ffmpeg"]))
        self.form.text(root, "FFprobe", "ffprobe", str(settings["ffprobe"]))
        self.form.text(root, "Browser", "browser", str(settings["browser"]))
        self.form.choice(
            root, "YouTube attestation mode", "youtube_attestation_mode",
            ["none", "po-token", "bgutil"], str(settings["youtube_attestation_mode"]),
        )
        cast(wx.Choice, self.values["youtube_attestation_mode"]).Bind(
            wx.EVT_CHOICE, self.update_attestation_fields,
        )
        self.po_token_row = self.form.text(root, "PO token", "po_token", str(settings["po_token"]))
        self.bgutil_row = self.form.text(root, "bgutil attestation URL", "bgutil_url", str(settings["bgutil_url"]))

        self.form.section(root, "World Stage API")
        self.form.text(
            root, "Song API token", "song_api_token", str(settings["song_api_token"]),
            style=wx.TE_PASSWORD,
        )

        self.form.section(root, "Cards and encoding")
        self.form.text(root, "AV1 preset", "av1_preset", str(settings["av1_preset"]))
        self.form.text(root, "AV1 CRF", "av1_crf", str(settings["av1_crf"]))
        self.form.text(root, "AV1 threads (0=auto)", "av1_threads", str(settings["av1_threads"]))
        self.form.text(root, "Opus bitrate", "opus_bitrate", str(settings["opus_bitrate"]))
        self.form.choice(root, "Audio normalization", "audio_normalization", ["none", "one-pass", "two-pass"], str(settings["audio_normalization"]))
        self.form.text(root, "Render jobs (0=auto)", "jobs", str(settings["jobs"]))

        self.form.section(root, "S3 uploads")
        try:
            s3 = prepare.load_s3_config()
            endpoint, bucket, profile = s3.endpoint_url, s3.bucket, s3.profile
        except prepare.S3NotConfigured:
            endpoint, bucket, profile = "", "", ""
        self.s3_endpoint = wx.TextCtrl(self, value=endpoint)
        self.s3_bucket = wx.TextCtrl(self, value=bucket)
        self.s3_profile = wx.TextCtrl(self, value=profile)
        self.form.control(root, "Endpoint URL", self.s3_endpoint)
        self.form.control(root, "Bucket", self.s3_bucket)
        self.form.control(root, "AWS profile", self.s3_profile)

        self.save_button = wx.Button(self, label="Save persistent settings")
        self.save_button.Bind(wx.EVT_BUTTON, self.save)
        root.Add(self.save_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 12)
        self.status = wx.StaticText(self, label=f"Configuration file: {app_config.config_path()}")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(root)
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)
        self.update_attestation_fields()

    def setting_values(self) -> dict[str, str | bool]:
        return cast(dict[str, str | bool], self.form.values_as_dict())

    def update_attestation_fields(self, _event=None) -> None:
        mode = cast(wx.Choice, self.values["youtube_attestation_mode"]).GetStringSelection()
        self.root_sizer.Show(self.po_token_row, mode == "po-token", recursive=True)
        self.root_sizer.Show(self.bgutil_row, mode == "bgutil", recursive=True)
        self.root_sizer.Layout()
        self.Layout()
        self.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=False)

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
            raise
        self.on_saved(app_config.recap_settings())
        self.status.SetLabel(f"Saved persistent settings to {path}.")


class RecapFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="World Stage Recap Maker", size=wx.Size(1100, 820))
        self.SetMinSize(wx.Size(820, 620))
        notebook = wx.Notebook(self)
        self.config_panel = ConfigPanel(notebook)
        editor = ShowEditorPanel(notebook, self.config_panel.set_input_path)
        self.prepare_panel = PreparePanel(notebook)
        self.batch_download_panel = BatchDownloadPanel(notebook)
        settings = SettingsPanel(notebook, self.apply_settings)
        notebook.AddPage(self.config_panel, "Configuration")
        notebook.AddPage(editor, "Show editor")
        notebook.AddPage(self.prepare_panel, "Prepare media")
        notebook.AddPage(self.batch_download_panel, "Batch download")
        notebook.AddPage(settings, "Settings")

    def apply_settings(self, settings: dict[str, str | bool]) -> None:
        self.config_panel.apply_persistent_settings(settings)
        self.config_panel.refresh_upload_availability()
        self.prepare_panel.refresh_upload_availability()
        self.batch_download_panel.refresh_upload_availability()


def start() -> None:
    app = wx.App(False)
    frame = RecapFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    start()
