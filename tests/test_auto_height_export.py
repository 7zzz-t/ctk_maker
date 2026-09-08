"""Exporter behaviour for first-class auto-height (spec §11).

extra height_mode=auto containers export WITHOUT a constructor height
kwarg (runtime height is content-driven); legacy height==0 frames keep
the historic height=0 emit so 02 output stays byte-identical with stock
00 on those files.
"""
from __future__ import annotations

from app.core.document import Document
from app.core.project import Project
from app.core.widget_node import WidgetNode
from app.io.code_exporter import generate_code


def _project_with_frame(height, extra=None):
    project = Project()
    doc = Document(name="MainWindow")
    doc.window_properties["width"] = 600
    doc.window_properties["height"] = 400
    project.documents = [doc]
    project.active_document_id = doc.id
    frame = WidgetNode("CTkFrame", {
        "x": 10, "y": 10, "width": 100, "height": height,
        "layout_type": "place", "fg_color": "#2b2b2b",
    })
    if extra is not None:
        frame.extra = dict(extra)
    project.add_widget(frame, document_id=doc.id)
    return project, frame


def test_first_class_auto_omits_height_kwarg():
    # height_mode=auto with a snapshot height (150): runtime height is
    # content-driven, so the constructor must NOT pin height=150.
    project, _frame = _project_with_frame(150, {"height_mode": "auto"})
    code = generate_code(project)
    assert "height=150" not in code
    assert "height=" not in code


def test_fixed_height_still_emitted():
    project, _frame = _project_with_frame(150)
    code = generate_code(project)
    assert "height=150" in code


def test_legacy_zero_keeps_historic_emit():
    # height==0 (no extra) keeps height=0 in the output — byte-identical
    # with what stock 00 emits for the same file.
    project, _frame = _project_with_frame(0)
    code = generate_code(project)
    assert "height=0" in code
