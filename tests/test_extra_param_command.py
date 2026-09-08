"""ExtraParamCommand — one undo step for first-class 02 enhancement
params (WidgetNode.extra, x.-prefixed UI rows)."""
from __future__ import annotations

from app.core.commands import ExtraParamCommand
from app.core.document import Document
from app.core.project import Project
from app.core.widget_node import WidgetNode


def _project_with_frame():
    project = Project()
    doc = Document(name="MainWindow")
    doc.window_properties["width"] = 400
    doc.window_properties["height"] = 300
    project.documents = [doc]
    project.active_document_id = doc.id
    frame = WidgetNode("CTkFrame", properties={
        "x": 0, "y": 0, "width": 100, "height": 150,
        "layout_type": "place",
    })
    project.add_widget(frame, document_id=doc.id)
    return project, frame


def test_redo_applies_after_extra_undo_restores_before():
    project, frame = _project_with_frame()
    before = {}
    after = {"height_mode": "auto", "main_axis": {"mode": "remain"}}
    cmd = ExtraParamCommand(frame.id, before, after)
    cmd.redo(project)
    assert project.get_widget(frame.id).extra == after
    cmd.undo(project)
    assert project.get_widget(frame.id).extra == before


def test_extra_never_leaks_into_properties():
    project, frame = _project_with_frame()
    cmd = ExtraParamCommand(
        frame.id, {}, {"height_mode": "auto"},
    )
    cmd.redo(project)
    node = project.get_widget(frame.id)
    assert "height_mode" not in node.properties
    assert "extra" not in node.properties


def test_description():
    cmd = ExtraParamCommand("w", {}, {"height_mode": "auto"})
    assert "enhancement parameter" in cmd.description
