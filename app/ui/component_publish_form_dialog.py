"""Modal — Publish-to-community form. Runs after the License dialog
has been accepted. Embeds an immutable ``license`` block (signed by
the typed Author at the moment of export) into the new ``.ctkcomp``
file written at the chosen folder.
"""

from __future__ import annotations

import datetime
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from app.core.component_paths import (
    COMPONENT_EXT, PUBLISH_COMPONENT_EXT, component_display_stem,
)
from app.core.i18n import tr
from app.ui.dialogs.message import ask_yes_no, show_error, show_warning
from app.ui.system_fonts import ui_font
from app.core.logger import log_error
from app.core.settings import load_settings, save_setting
from app.io.component_io import load_metadata, rewrite_payload_for_publish
from app.ui.managed_window import ManagedToplevel

CATEGORY_GUIDE_URL = (
    "https://github.com/kandelucky/ctk_maker/wiki/Component-Categories"
)

LAST_AUTHOR_KEY = "last_component_author"
LICENSE_TEXT_VERSION = 1
DESCRIPTION_MAX = 300
# Hub site upload cap — temporary GitHub Discussions attachment limit.
PUBLISH_MAX_BYTES = 25 * 1024 * 1024

CATEGORIES: list[tuple[str, str]] = [
    ("Buttons", "Styled buttons (icon, toggle packs, action groups)"),
    ("Inputs", "Entry / Combobox / Checkbox / Slider variations"),
    ("Forms", "Multi-field configurations (login, signup, settings, contact)"),
    ("Layout", "Grid / row / column containers, splitters, scroll areas"),
    ("Navigation", "Sidebar, top bar, tab strip, breadcrumb, menu drawer"),
    ("Dialogs & Modals", "Alerts, confirms, file pickers, settings popups"),
    ("Cards & Panels", "Info card, profile card, stat tile, collapsible panel"),
    ("Mini-Apps", "Full small apps (todo, calculator, calendar, music player)"),
    ("Templates & Starters", "Empty skeletons for new projects"),
    ("Other", "Anything that doesn't fit elsewhere"),
]
CATEGORY_HINTS = {name: hint for name, hint in CATEGORIES}

_FORBIDDEN = set('\\/:*?"<>|')


def _is_valid_name(name: str) -> bool:
    name = name.strip()
    if not name or name in (".", ".."):
        return False
    return not any(ch in _FORBIDDEN for ch in name)


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    kb = num_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.1f} MB"


def _format_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


class ComponentPublishFormDialog(ManagedToplevel):
    default_size = (440, 600)
    min_size = (420, 560)
    fg_color = "#1a1a1a"
    panel_padding = (0, 0)
    modal = True
    window_resizable = (False, False)

    def __init__(self, parent, source_path: Path):
        self.window_title = tr("comp_publish.title", "Publish component")
        self.result: bool = False
        self._source_path = source_path
        self._destination: Path | None = None
        self._meta = load_metadata(source_path) or {}
        try:
            self._file_bytes = source_path.stat().st_size
        except OSError:
            self._file_bytes = 0
        cached_author = str(
            load_settings().get(LAST_AUTHOR_KEY, "") or "",
        )
        self._cached_author = cached_author
        self._name_var = tk.StringVar(
            master=parent, value=component_display_stem(source_path),
        )
        self._author_var = tk.StringVar(
            master=parent,
            value=self._meta.get("author", "") or cached_author,
        )
        self._category_names = [name for name, _ in CATEGORIES]
        self._category_display = [
            tr(f"comp_publish.category.{name}", name)
            for name in self._category_names
        ]
        self._category_by_display = {
            display: name
            for display, name in zip(self._category_display, self._category_names)
        }
        self._category_var = tk.StringVar(
            master=parent, value=self._category_display[0],
        )
        self._dest_var = tk.StringVar(master=parent, value="")
        super().__init__(parent)

    def default_offset(self, parent) -> tuple[int, int]:
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w, h = self.default_size
            return (
                max(0, px + (pw - w) // 2),
                max(0, py + (ph - h) // 2),
            )
        except tk.TclError:
            return (100, 100)

    def build_content(self) -> ctk.CTkFrame:
        container = ctk.CTkFrame(self, fg_color="transparent")
        meta = self._meta

        body = ctk.CTkFrame(container, fg_color="transparent")
        body.pack(padx=22, pady=(18, 6), fill="x")

        ctk.CTkLabel(
            body,
            text=meta.get("name") or component_display_stem(self._source_path),
            font=ui_font(14, "bold"),
            text_color="#e6e6e6", anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            body,
            text=(
                f"{meta.get('view_w', 0)} × {meta.get('view_h', 0)}"
                f"  ·  {_format_size(self._file_bytes)}"
                f"  ·  {_format_date(meta.get('created_at', ''))}"
            ),
            font=ui_font(9),
            text_color="#888888", anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        # License banner — reminder of what was just agreed to.
        banner = ctk.CTkFrame(
            body, fg_color="#262a30", corner_radius=4,
        )
        banner.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(
            banner,
            text=tr("comp_publish.license_banner", "✓ License agreement accepted — MIT  ·  signed at export"),
            font=ui_font(9, "bold"),
            text_color="#9ec3ff", anchor="w",
        ).pack(anchor="w", padx=10, pady=6)

        ctk.CTkLabel(
            body, text=tr("comp_publish.name", "Name"), font=ui_font(10),
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))
        ctk.CTkEntry(
            body, textvariable=self._name_var, width=340,
        ).grid(row=4, column=0, sticky="ew", pady=(0, 12))

        ctk.CTkLabel(
            body, text=tr("comp_publish.author", "Author (required — used as MIT copyright holder)"),
            font=ui_font(10),
        ).grid(row=5, column=0, sticky="w", pady=(0, 4))
        ctk.CTkEntry(
            body, textvariable=self._author_var, width=340,
            placeholder_text=tr("comp_publish.author_placeholder", "your name or handle"),
        ).grid(row=6, column=0, sticky="ew", pady=(0, 12))

        cat_label_row = ctk.CTkFrame(body, fg_color="transparent")
        cat_label_row.grid(row=7, column=0, sticky="ew", pady=(0, 4))
        cat_label_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            cat_label_row, text=tr("comp_publish.category", "Category"), font=ui_font(10),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            cat_label_row, text=tr("comp_publish.need_help", "Need help picking?"),
            width=130, height=20, corner_radius=3,
            font=ui_font(9, "underline"),
            fg_color="transparent", hover_color="#2b2b2b",
            text_color="#9ec3ff",
            command=self._open_category_guide,
        ).grid(row=0, column=1, sticky="e")
        self._category_menu = ctk.CTkOptionMenu(
            body, values=self._category_display,
            variable=self._category_var, width=340,
            command=lambda _v: self._refresh_category_hint(),
        )
        self._category_menu.grid(row=8, column=0, sticky="ew", pady=(0, 2))
        self._category_hint = ctk.CTkLabel(
            body, text="", font=ui_font(9),
            text_color="#888888", anchor="w", justify="left",
        )
        self._category_hint.grid(
            row=9, column=0, sticky="w", pady=(0, 12),
        )
        self._refresh_category_hint()

        ctk.CTkLabel(
            body, text=tr("comp_publish.description", "Description"), font=ui_font(10),
        ).grid(row=10, column=0, sticky="w", pady=(0, 4))
        self._desc_box = ctk.CTkTextbox(
            body, height=70, width=340,
            font=ui_font(10), wrap="word",
        )
        self._desc_box.grid(row=11, column=0, sticky="ew", pady=(0, 2))
        self._desc_box.bind(
            "<KeyRelease>", lambda _e: self._refresh_desc_counter(),
        )
        self._desc_counter = ctk.CTkLabel(
            body, text=tr("comp_publish.desc_counter", "{count} / {max}").format(count=0, max=DESCRIPTION_MAX),
            font=ui_font(9), text_color="#888888", anchor="e",
        )
        self._desc_counter.grid(row=12, column=0, sticky="e", pady=(0, 12))

        ctk.CTkLabel(
            body, text=tr("comp_publish.destination_folder", "Destination folder"), font=ui_font(10),
        ).grid(row=13, column=0, sticky="w", pady=(0, 4))
        path_row = ctk.CTkFrame(body, fg_color="transparent")
        path_row.grid(row=14, column=0, sticky="ew", pady=(0, 12))
        path_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            path_row, textvariable=self._dest_var,
            placeholder_text=tr("comp_publish.pick_folder", "(pick a folder)"), height=28,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(
            path_row, text=tr("comp_publish.browse", "Browse…"), width=80, height=28,
            corner_radius=4, command=self._on_browse,
        ).grid(row=0, column=1)

        body.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(container, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=(4, 16))
        ctk.CTkButton(
            footer, text=tr("comp_publish.publish", "Publish"), width=130, height=32,
            corner_radius=4, command=self._on_publish,
        ).pack(side="right")
        ctk.CTkButton(
            footer, text=tr("comp_publish.cancel", "Cancel"), width=90, height=32,
            corner_radius=4,
            fg_color="#3c3c3c", hover_color="#4a4a4a",
            command=self._on_cancel,
        ).pack(side="right", padx=(0, 8))
        return container

    def _open_category_guide(self) -> None:
        import webbrowser
        try:
            webbrowser.open(CATEGORY_GUIDE_URL, new=2)
        except Exception:
            pass

    def _refresh_category_hint(self) -> None:
        display = self._category_var.get()
        name = self._category_by_display.get(display)
        hint = CATEGORY_HINTS.get(name, "") if name else ""
        self._category_hint.configure(
            text=tr(f"comp_publish.category_hint.{name}", hint) if name else "",
        )

    def _refresh_desc_counter(self) -> None:
        text = self._desc_box.get("1.0", "end-1c")
        if len(text) > DESCRIPTION_MAX:
            self._desc_box.delete(f"1.0+{DESCRIPTION_MAX}c", "end")
            text = text[:DESCRIPTION_MAX]
        n = len(text)
        color = "#d68a40" if n >= DESCRIPTION_MAX else "#888888"
        self._desc_counter.configure(
            text=tr("comp_publish.desc_counter", "{count} / {max}").format(count=n, max=DESCRIPTION_MAX),
            text_color=color,
        )

    def _on_browse(self) -> None:
        path = filedialog.askdirectory(
            parent=self,
            title=tr("comp_publish.browse_title", "Publish component — pick destination folder"),
        )
        if not path:
            return
        self._dest_var.set(path)

    def _on_publish(self) -> None:
        try:
            source_size = self._source_path.stat().st_size
        except OSError:
            source_size = 0
        if source_size > PUBLISH_MAX_BYTES:
            self.bell()
            show_warning(
                tr("comp_publish.too_large_title", "Too large to publish"),
                tr(
                    "comp_publish.too_large_msg",
                    "This component is {size}. The community site currently "
                    "accepts files up to 25 MB. You can still save it for "
                    "personal use.",
                ).format(size=_format_size(source_size)),
                parent=self,
            )
            return
        author = self._author_var.get().strip()
        if not author:
            self.bell()
            show_warning(
                tr("comp_publish.author_required_title", "Author required"),
                tr(
                    "comp_publish.author_required_msg",
                    "Author can't be empty — it's used as the MIT copyright holder.",
                ),
                parent=self,
            )
            return
        category_display = self._category_var.get().strip()
        category = self._category_by_display.get(category_display)
        if category is None:
            self.bell()
            show_warning(
                tr("comp_publish.pick_category_title", "Pick a category"),
                tr("comp_publish.pick_category_msg", "Pick a category from the dropdown."),
                parent=self,
            )
            return
        description = self._desc_box.get("1.0", "end-1c").strip()
        if not description:
            self.bell()
            show_warning(
                tr("comp_publish.desc_required_title", "Description required"),
                tr(
                    "comp_publish.desc_required_msg",
                    "Add a brief description so other users know what this component does.",
                ),
                parent=self,
            )
            return
        dest = self._dest_var.get().strip()
        if not dest:
            self.bell()
            show_warning(
                tr("comp_publish.pick_dest_title", "Pick a destination"),
                tr("comp_publish.pick_dest_msg", "Click Browse… to choose a destination folder."),
                parent=self,
            )
            return
        name = self._name_var.get().strip()
        # Strip whichever component suffix the user may have typed —
        # we re-append the canonical Hub-upload one below.
        for ext in (PUBLISH_COMPONENT_EXT, COMPONENT_EXT):
            if name.lower().endswith(ext):
                name = name[: -len(ext)]
                break
        if not _is_valid_name(name):
            self.bell()
            show_warning(
                tr("comp_publish.invalid_name_title", "Invalid name"),
                tr("comp_publish.invalid_name_msg", "Names can't be empty or contain \\ / : * ? \" < > |."),
                parent=self,
            )
            return
        dest_dir = Path(dest)
        if not dest_dir.is_dir():
            self.bell()
            show_warning(
                tr("comp_publish.folder_not_found_title", "Folder not found"),
                tr(
                    "comp_publish.folder_not_found_msg",
                    "'{path}' is not a folder. Pick another destination.",
                ).format(path=dest_dir),
                parent=self,
            )
            return
        dest_path = dest_dir / f"{name}{PUBLISH_COMPONENT_EXT}"
        if dest_path.exists():
            overwrite = ask_yes_no(
                tr("comp_publish.exists_title", "Already exists"),
                tr(
                    "comp_publish.exists_msg",
                    "'{name}' already exists in this folder. Overwrite?",
                ).format(name=dest_path.name),
                parent=self,
            )
            if not overwrite:
                return

        try:
            shutil.copy2(self._source_path, dest_path)
        except OSError as exc:
            log_error(f"publish copy {self._source_path} -> {dest_path}")
            self.bell()
            show_error(
                tr("comp_publish.copy_failed_title", "Copy failed"),
                tr(
                    "comp_publish.copy_failed_msg",
                    "Couldn't write the file:\n{error}",
                ).format(error=exc),
                parent=self,
            )
            return

        license_block = self._build_license_block(author)
        try:
            rewrite_payload_for_publish(
                dest_path,
                author=author,
                license_block=license_block,
                category=category,
                description=description,
            )
        except Exception as exc:
            log_error(f"publish rewrite {dest_path}")
            self.bell()
            show_error(
                tr("comp_publish.license_embed_failed_title", "License embed failed"),
                tr(
                    "comp_publish.license_embed_failed_msg",
                    "The component was copied but the license block couldn't be written:\n{error}",
                ).format(error=exc),
                parent=self,
            )
            return

        if author and author != self._cached_author:
            save_setting(LAST_AUTHOR_KEY, author)

        self._destination = dest_path
        self.result = True
        self.destroy()

    def _build_license_block(self, author: str) -> dict:
        try:
            from app import __version__ as app_version
        except ImportError:
            app_version = "unknown"
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        return {
            "type": "MIT",
            "accepted_by": author,
            "accepted_at": now_utc.isoformat(timespec="seconds").replace(
                "+00:00", "Z",
            ),
            "ctk_maker_version": app_version,
            "confirmations": {
                "rights": True,
                "mit_release": True,
                "responsibility": True,
            },
            "text_version": LICENSE_TEXT_VERSION,
        }

    def _on_cancel(self) -> None:
        self.result = False
        self.destroy()
