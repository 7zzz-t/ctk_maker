"""Folder / file creation + rename / delete sidecar for ``ProjectPanel``.

Owns every action that creates, renames, or removes a file or
folder under ``assets/``:

* ``on_new_folder`` — prompt for a name, create directory at
  ``resolve_target_dir()`` (right-clicked folder wins, else
  assets root).
* ``on_new_text_file`` / ``on_new_python_file`` — shared
  ``create_text_file`` helper with per-kind defaults (.md / .py),
  extension coercion, and starter template.
* ``on_rename`` — file or folder rename with forbidden-char +
  collision guard.
* ``on_delete_folder`` — recursive delete with read-only-flag
  workaround for Windows + post-delete verification.
* ``remove_asset`` — single-file delete with font cascade purge
  for fonts so cached registrations clear.
* ``reimport_asset`` — replace an existing asset's content in
  place (path stays, references keep working).

Every action ends with a ``dirty_changed`` event-bus publish + a
``panel.refresh()`` so the tree picks up the disk-level change.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from tkinter import filedialog

from app.core.i18n import tr
from app.core.logger import log_error
from app.ui.dialogs.message import ask_string, ask_yes_no, show_error, show_warning


_FORBIDDEN_NAME_CHARS = set('\\/:*?"<>|')


class ProjectPanelFiles:
    """File / folder lifecycle helpers. See module docstring."""

    def __init__(self, panel) -> None:
        self.panel = panel

    def on_new_folder(self) -> None:
        panel = self.panel
        target = panel._resolve_target_dir()
        if target is None:
            return
        name = ask_string(
            tr("project_files.new_folder_title", "New folder"),
            tr("project_files.folder_name_label", "Folder name:"),
            parent=panel.winfo_toplevel(),
        )
        if not name:
            return
        name = name.strip()
        if not name or set(name) & _FORBIDDEN_NAME_CHARS:
            show_warning(
                tr("project_files.invalid_name_title", "Invalid name"),
                tr("project_files.invalid_folder_name_msg",
                   "Folder name contains forbidden characters or is empty."),
                parent=panel.winfo_toplevel(),
            )
            return
        new_dir = target / name
        if new_dir.exists():
            show_warning(
                tr("project_files.folder_exists_title", "Folder exists"),
                tr("project_files.folder_exists_msg",
                   "'{name}' already exists in this location.").format(name=name),
                parent=panel.winfo_toplevel(),
            )
            return
        try:
            new_dir.mkdir(parents=True)
        except OSError:
            log_error("new folder mkdir")
            show_error(
                tr("project_files.new_folder_failed_title", "New folder failed"),
                tr("project_files.create_failed_msg",
                   "Couldn't create:\n{path}").format(path=new_dir),
                parent=panel.winfo_toplevel(),
            )
            return
        panel.project.event_bus.publish("dirty_changed", True)
        panel.refresh()

    def on_new_text_file(self) -> None:
        self.create_text_file(
            kind="text",
            default_name=tr("project_files.notes_default_name", "NOTES"),
            allowed_exts=(".md", ".txt"),
            default_ext=".md",
            initial_content_for=lambda stem: f"# {stem}\n\n",
            dialog_title=tr("project_files.new_text_file_title", "New text file"),
            error_label=tr("project_files.text_file_label", "text file"),
        )

    def on_new_python_file(self) -> None:
        # Starter docstring sets clear expectations about v0.1
        # behaviour-layer status, points users at the issue tracker
        # for prioritisation, and threads the support link. Plain
        # text (no emoji) so Windows default fonts render it
        # cleanly across every editor.
        from app.ui.project_window import _python_starter_template
        self.create_text_file(
            kind="code",
            default_name=tr("project_files.script_default_name", "script"),
            allowed_exts=(".py",),
            default_ext=".py",
            initial_content_for=_python_starter_template,
            dialog_title=tr("project_files.new_python_file_title", "New Python file"),
            error_label=tr("project_files.python_file_label", "Python file"),
        )

    def create_text_file(
        self,
        *,
        kind: str,
        default_name: str,
        allowed_exts: tuple[str, ...],
        default_ext: str,
        initial_content_for,
        dialog_title: str,
        error_label: str,
    ) -> None:
        """Shared body for ``on_new_text_file`` / ``on_new_python_file``
        (and any future text-class file the panel adds). Same prompt
        + extension-coercion + write-and-open flow with a per-kind
        starter template.
        """
        panel = self.panel
        target = panel._resolve_target_dir()
        if target is None:
            return
        name = ask_string(
            dialog_title,
            tr("project_files.filename_label", "Filename (without extension):"),
            initialvalue=default_name,
            parent=panel.winfo_toplevel(),
        )
        if not name:
            return
        name = name.strip()
        if not name or set(name) & _FORBIDDEN_NAME_CHARS:
            show_warning(
                tr("project_files.invalid_name_title", "Invalid name"),
                tr("project_files.invalid_filename_msg",
                   "Filename contains forbidden characters or is empty."),
                parent=panel.winfo_toplevel(),
            )
            return
        if not name.lower().endswith(allowed_exts):
            name = f"{name}{default_ext}"
        new_file = target / name
        if new_file.exists():
            show_warning(
                tr("project_files.file_exists_title", "File exists"),
                tr("project_files.file_exists_msg",
                   "'{name}' already exists in this location.").format(name=name),
                parent=panel.winfo_toplevel(),
            )
            return
        try:
            target.mkdir(parents=True, exist_ok=True)
            new_file.write_text(
                initial_content_for(Path(name).stem),
                encoding="utf-8",
            )
        except OSError:
            log_error(f"new {error_label} write")
            show_error(
                tr("project_files.new_file_failed_title",
                   "New {label} failed").format(label=error_label),
                tr("project_files.create_failed_msg",
                   "Couldn't create:\n{path}").format(path=new_file),
                parent=panel.winfo_toplevel(),
            )
            return
        panel.project.event_bus.publish("dirty_changed", True)
        panel.refresh()
        # No auto-open. The user just typed a filename and clicked
        # OK — they expect to see the file land in the tree, not
        # for the OS to immediately steal focus into VSCode /
        # Notepad. Double-click on the row opens it when the user
        # is ready.

    def on_rename(self) -> None:
        panel = self.panel
        meta = panel._selected_meta()
        if meta is None:
            return
        old_path, kind = meta
        new_name = ask_string(
            tr("project_files.rename_title", "Rename"),
            tr("project_files.new_name_label", "New name:"),
            initialvalue=old_path.name,
            parent=panel.winfo_toplevel(),
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_path.name:
            return
        if set(new_name) & _FORBIDDEN_NAME_CHARS:
            show_warning(
                tr("project_files.invalid_name_title", "Invalid name"),
                tr("project_files.invalid_name_msg",
                   "Name contains forbidden characters."),
                parent=panel.winfo_toplevel(),
            )
            return
        new_path = old_path.parent / new_name
        if new_path.exists():
            show_warning(
                tr("project_files.already_exists_title", "Already exists"),
                tr("project_files.already_exists_msg",
                   "'{name}' already exists.").format(name=new_name),
                parent=panel.winfo_toplevel(),
            )
            return
        try:
            old_path.rename(new_path)
        except OSError:
            log_error("rename asset")
            show_error(
                tr("project_files.rename_failed_title", "Rename failed"),
                tr("project_files.rename_failed_msg",
                   "Couldn't rename:\n{old_path}\n→\n{new_path}").format(
                    old_path=old_path, new_path=new_path,
                ),
                parent=panel.winfo_toplevel(),
            )
            return
        # File renames break references in widget properties (image
        # paths) — let the workspace re-render so missing files fall
        # back to defaults gracefully.
        panel.project.event_bus.publish("dirty_changed", True)
        panel.project.event_bus.publish(
            "font_defaults_changed", panel.project.font_defaults,
        )
        panel.refresh()

    def on_delete_folder(self) -> None:
        from app.ui.project_window import _force_remove_readonly
        panel = self.panel
        meta = panel._selected_meta()
        if meta is None or meta[1] != "folder":
            return
        folder = meta[0]
        # Count contents so the warning carries weight on big trees.
        try:
            count = sum(1 for _ in folder.rglob("*"))
        except OSError:
            count = 0
        if not ask_yes_no(
            tr("project_files.delete_folder_title", "Delete folder"),
            tr("project_files.delete_folder_msg",
               "Delete '{name}' and {count} item(s) inside it?\n\n"
               "Path: {path}\n\n"
               "This deletes the folder from disk and cannot be undone. "
               "Widgets that referenced any of these files fall back to "
               "a default at the next render.").format(
                name=folder.name, count=count, path=folder,
            ),
            parent=panel.winfo_toplevel(),
            danger=True,
            yes_text=tr("project_files.delete_yes", "Delete"),
            no_text=tr("project_files.cancel", "Cancel"),
        ):
            return
        try:
            # ``onerror`` flips read-only attributes + retries —
            # without it Windows refuses to delete folders that
            # got marked read-only by tools like git or git-lfs,
            # and shutil.rmtree errors out silently in some
            # callers' eyes.
            shutil.rmtree(folder, onerror=_force_remove_readonly)
        except Exception:
            log_error("delete folder rmtree")
            show_error(
                tr("project_files.delete_failed_title", "Delete failed"),
                tr("project_files.delete_failed_msg",
                   "Couldn't delete:\n{path}\n\nThe folder may be open "
                   "in another program (Explorer window, terminal). "
                   "Close it and try again.").format(path=folder),
                parent=panel.winfo_toplevel(),
            )
            return
        # Confirm the folder is actually gone — rmtree can sometimes
        # complete partially without raising on Windows.
        if folder.exists():
            log_error(f"delete folder still exists: {folder}")
            show_error(
                tr("project_files.delete_failed_title", "Delete failed"),
                tr("project_files.delete_still_exists_msg",
                   "The folder couldn't be removed:\n{path}\n\n"
                   "It may be open in Explorer or a terminal. "
                   "Close those windows and try again.").format(path=folder),
                parent=panel.winfo_toplevel(),
            )
            return
        panel.project.event_bus.publish("dirty_changed", True)
        panel.project.event_bus.publish(
            "font_defaults_changed", panel.project.font_defaults,
        )
        panel.refresh()

    def remove_asset(self, file_path: Path, kind: str) -> None:
        """Delete an asset from disk after a single irreversible-action
        warning. References on widgets or in the font cascade fall
        back to Tk / CTk defaults at next render — descriptors already
        try/except around image loads, and Tk silently substitutes
        unknown font families. Skipping the project-wide reference
        scan keeps the dialog instant on big projects.
        """
        from app.ui.project_window import _read_font_family
        panel = self.panel
        if not ask_yes_no(
            tr("project_files.remove_asset_title", "Remove asset"),
            tr("project_files.remove_asset_msg",
               "Remove '{name}' from the project?\n\n"
               "File: {path}\n\n"
               "This deletes the file from disk and cannot be undone. "
               "Widgets that referenced this asset fall back to a "
               "default at the next render.").format(
                name=file_path.name, path=file_path,
            ),
            parent=panel.winfo_toplevel(),
            danger=True,
            yes_text=tr("project_files.remove_yes", "Remove"),
            no_text=tr("project_files.cancel", "Cancel"),
        ):
            return
        # Resolve the font family BEFORE unlinking — once the file is
        # gone PIL can't read its name table and the cleanup pass
        # below would silently skip system_fonts / cascade / per-widget
        # references.
        family_to_purge: str | None = None
        if kind == "fonts":
            family_to_purge = _read_font_family(file_path)
        try:
            file_path.unlink()
        except OSError:
            log_error("remove asset unlink")
            show_error(
                tr("project_files.remove_failed_title", "Remove failed"),
                tr("project_files.delete_failed_msg",
                   "Couldn't delete:\n{path}").format(path=file_path),
                parent=panel.winfo_toplevel(),
            )
            return
        if family_to_purge:
            from app.core.fonts import purge_family_from_project
            purge_family_from_project(panel.project, family_to_purge)
        panel.project.event_bus.publish("dirty_changed", True)
        # Force a re-render so references that became stale (image
        # widgets pointing at a deleted file, font cascade entries
        # pointing at an uninstalled family) refresh to fallbacks.
        panel.project.event_bus.publish(
            "font_defaults_changed", panel.project.font_defaults,
        )
        panel.refresh()

    def reimport_asset(self, file_path: Path, kind: str) -> None:
        """Replace an existing asset's content in place — useful when
        the user has an updated version on disk (e.g. higher-res icon)
        and wants the swap to ripple through the whole project
        without renaming or rewiring anything. Path stays the same so
        every widget reference keeps working.
        """
        from app.ui.project_window import ASSET_KINDS
        panel = self.panel
        exts, filter_spec = ASSET_KINDS[kind]
        src = filedialog.askopenfilename(
            parent=panel.winfo_toplevel(),
            title=tr("project_files.reimport_title",
                     "Reimport {name}").format(name=file_path.name),
            filetypes=[
                filter_spec,
                (tr("project_files.all_files", "All files"), "*.*"),
            ],
        )
        if not src:
            return
        src_path = Path(src)
        if src_path.suffix.lower() not in exts:
            show_warning(
                tr("project_files.wrong_file_type_title", "Wrong file type"),
                tr("project_files.wrong_file_type_msg",
                   "Picked file's extension doesn't match the asset's "
                   "kind ({kind}). Reimport keeps the existing filename, "
                   "so the new file's content must be the same kind."
                   ).format(kind=kind),
                parent=panel.winfo_toplevel(),
            )
            return
        try:
            shutil.copy2(src_path, file_path)
        except OSError:
            log_error("reimport asset copy")
            show_error(
                tr("project_files.reimport_failed_title", "Reimport failed"),
                tr("project_files.reimport_failed_msg",
                   "Couldn't copy:\n{src_path}\n→\n{dst_path}").format(
                    src_path=src_path, dst_path=file_path,
                ),
                parent=panel.winfo_toplevel(),
            )
            return
        # Tkextrafont is per-file-path: re-register so the running Tk
        # interpreter picks up the new bytes without a relaunch.
        if kind == "fonts":
            try:
                from app.core.fonts import (
                    _loaded_files, register_font_file,
                )
                _loaded_files.pop(file_path.resolve(), None)
                register_font_file(
                    file_path, root=panel.winfo_toplevel(),
                )
            except Exception:
                log_error("reimport font register")
        panel.project.event_bus.publish("dirty_changed", True)
        # Trigger a re-render — image widgets need their CTkImage
        # rebuilt against the new file content.
        panel.project.event_bus.publish(
            "font_defaults_changed", panel.project.font_defaults,
        )
        panel.refresh()
