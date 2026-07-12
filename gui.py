#!/usr/bin/env python3
"""Start the preferred wxPython UI, falling back to Tk when wx is absent."""

# pyright: reportMissingImports=false

from __future__ import annotations


def start() -> None:
    try:
        import wx  # noqa: F401
    except ImportError:
        from gui import start as start_tk

        start_tk()
        return

    from gui_wx import start as start_wx

    start_wx()


if __name__ == "__main__":
    start()
