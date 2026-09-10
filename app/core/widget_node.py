import copy
import uuid

# Backwards-compat widget type renames. Older ``.ctkproj`` files
# stored the historical type name; on load we silently translate to
# the current one so existing projects don't break after a rename.
# Rename only — kwargs / properties are unchanged across these mappings.
_WIDGET_TYPE_RENAMES = {
    "Shape": "Card",  # 2026-04-27: Shape → Card
}

# Single top-level carrier for ALL 02 builder-only enhancement params
# (see docs/LAYOUT_ENHANCEMENT_COMPAT.md §11). Kept out of
# ``properties``: stock 00 forwards every property key to the CTk
# constructor, so builder-only data must never ride that dict.
_CTKMETA_KEY = "_ctkmaker_meta"


def _bake_pack_child_disk(container, child, child_dict):
    """Spec §11.5 disk bake: derived size params (main-axis percent /
    remainder, cross-axis percent) serialize as a **plain number** in
    the child's own ``height`` / ``width`` row — exactly what a user
    would have typed by hand. ``stretch`` is deliberately left as the
    user set it (default ``fixed``), so stock 00 opens the same file and
    renders the layout identically. Returns ``child_dict`` (possibly
    rewritten)."""
    if child is None or not isinstance(child_dict, dict):
        return child_dict
    # Imported lazily: ``extra_params`` refers back to this module.
    from app.widgets.extra_params import (
        CROSS,
        MAIN,
        derived_axis_px,
        parent_axis_key,
    )
    layout = (container.properties or {}).get("layout_type") \
        if container is not None else None
    props = dict(child_dict.get("properties") or {})
    changed = False
    for axis in (MAIN, CROSS):
        px = derived_axis_px(child, axis)
        if px is None:
            continue
        key = parent_axis_key(layout, axis)
        if key is None or props.get(key) == px:
            continue
        props[key] = px
        changed = True
    if changed:
        child_dict["properties"] = props
    return child_dict


def clean_component_dict(raw) -> dict | None:
    """Validate one serialised CTkScript component entry from a
    ``.ctkproj``. Returns a fresh
    ``{"script", "class"[, "var_bindings"][, "field_values"]}`` dict, or
    ``None`` when ``script`` / ``class`` is missing or empty.

    A script's exposed field carries **one** source:
    - ``var_bindings`` — field → bound project variable **UUID**
      (rename-safe; the variable's display name can change freely), or
    - ``field_values`` — field → an inline literal value (a string;
      coerced to the field's tk Variable type at export).

    The editor keeps the two mutually exclusive per field. Malformed
    pairs are dropped and an empty map's key is omitted. Single source
    of truth for the on-disk component shape — used by both
    ``WidgetNode`` and ``Document`` loaders.
    See docs/plans/archive/script_variable_binding.md.
    """
    if not isinstance(raw, dict):
        return None
    script = raw.get("script")
    cls = raw.get("class")
    if not (isinstance(script, str) and script
            and isinstance(cls, str) and cls):
        return None

    def _str_map(m):
        if not isinstance(m, dict):
            return {}
        return {
            k: v for k, v in m.items()
            if isinstance(k, str) and k and isinstance(v, str) and v
        }

    out: dict = {"script": script, "class": cls}
    bindings = _str_map(raw.get("var_bindings"))
    if bindings:
        out["var_bindings"] = bindings
    values = _str_map(raw.get("field_values"))
    if values:
        out["field_values"] = values
    return out


class WidgetNode:
    def __init__(self, widget_type: str, properties: dict | None = None):
        self.id: str = str(uuid.uuid4())
        self.name: str = ""
        self.widget_type: str = widget_type
        self.properties: dict = dict(properties) if properties else {}
        self.children: list[WidgetNode] = []
        self.parent: WidgetNode | None = None
        # Parent-slot name for container parents whose tk master is a
        # named sub-widget rather than the container itself — currently
        # only CTkTabview (tab name). None for plain parents.
        self.parent_slot: str | None = None
        # Builder-only visibility flag. Hidden nodes still exist in the
        # model, still save/load, and still export — they just skip
        # rendering in the workspace so the editor stays uncluttered.
        self.visible: bool = True
        # Builder-only lock flag. Locked nodes can still be selected
        # (to view their properties) but reject drag / resize /
        # arrow-nudge / delete — protects background containers from
        # accidental edits. Cascades through descendants.
        self.locked: bool = False
        # Builder-only group tag. Widgets sharing a group_id are
        # selected together by a single click and are dragged /
        # deleted as one unit. Cross-parent groups are allowed —
        # group_id is metadata, not hierarchy. Skipped from code
        # export (the generated Python sees only individual widgets).
        self.group_id: str | None = None
        # Builder-only enhancement parameters (auto-height mode, main-
        # axis percent/remainder, …). Serialised as the single top-level
        # ``_ctkmaker_meta`` key; NEVER merged into ``properties`` (stock
        # 00 forwards every property key to the CTk constructor).
        # See docs/LAYOUT_ENHANCEMENT_COMPAT.md §11.
        self.extra: dict = {}
        # AI-bridge meta-property. Plain-language description of what
        # this widget should do. Emitted as Python comments above the
        # widget's constructor call in code export so an AI can read
        # the structure + intent and fill in the missing logic. Never
        # reaches CTk constructors.
        self.description: str = ""
        # CTkScript model — event handler bindings. Maps an event key
        # (``"command"`` for click-style; ``"bind:<seq>"`` for Tk
        # bind-style) to an ordered list of ``script_call`` entries.
        # Order is execution order — multi-entry binding fans out via a
        # lambda chain (constructor kwarg) or repeated ``.bind(seq, fn,
        # add="+")`` (Tk bind). Empty list = unbound.
        #
        # Each entry is a ``dict`` with ``{"kind": "script_call",
        # "class": <ClassName>, "method": <method_name>,
        # "scope": "widget"|"window"}`` — call a public method on a
        # CTkScript component attached to this widget (``scope="widget"``)
        # or the owning window (``scope="window"``). ``class`` must match
        # an entry in the relevant ``attached_components``; the script
        # path is resolved from there. See docs/plans/script_optimization.md.
        self.handlers: dict[str, list] = {}

        # CTkScript model — components (CTkScript subclasses) attached to
        # this widget. Each entry: ``{"script": <scripts/-relative
        # path>, "class": <ClassName>}``. A widget-attached component is
        # scoped to this widget (``self.widget``); CTkMaker instantiates
        # one per entry, calls ``on_start`` after build, and exposes its
        # public methods to event bindings. Multiple allowed (Unity:
        # many components per object).
        self.attached_components: list[dict] = []

    def to_dict(self) -> dict:
        # Shallow-copy ``properties`` so callers (project_saver
        # tokenisation, copy/paste snapshot, undo recording) can mutate
        # the returned dict without aliasing back into the live
        # widget. Without this, ``_walk_widget_tokenize`` rewrote
        # ``props["image"]`` to an ``asset:images/...`` token and the
        # canvas's PIL.open then choked on a path it couldn't read.
        props = dict(self.properties)
        result = {
            "id": self.id,
            "name": self.name,
            "widget_type": self.widget_type,
            "properties": props,
            "visible": self.visible,
            "locked": self.locked,
            "children": [
                _bake_pack_child_disk(self, c, c.to_dict())
                for c in self.children
            ],
        }
        if self.extra:
            result[_CTKMETA_KEY] = copy.deepcopy(dict(self.extra))
        if self.parent_slot is not None:
            result["parent_slot"] = self.parent_slot
        if self.group_id is not None:
            result["group_id"] = self.group_id
        if self.description:
            result["description"] = self.description
        # Drop empty lists so the .ctkproj stays compact for projects
        # that haven't bound anything; serialised handlers are always
        # ``{event: [entry, entry, ...]}`` lists, never strings.
        # Each entry is a ``script_call`` dict — deep-copy them so
        # callers (tokeniser, undo recorder, clipboard) can mutate the
        # returned snapshot without aliasing back into the live widget.
        emitted = {
            k: [
                copy.deepcopy(e) if isinstance(e, dict) else e
                for e in v
            ]
            for k, v in self.handlers.items()
            if v
        }
        if emitted:
            result["handlers"] = emitted
        if self.attached_components:
            result["attached_components"] = [
                dict(c) for c in self.attached_components
            ]
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "WidgetNode":
        raw_type: str = data["widget_type"]
        widget_type = _WIDGET_TYPE_RENAMES.get(raw_type, raw_type)
        node = cls(
            widget_type=widget_type,
            properties=data.get("properties", {}),
        )
        node.id = data["id"]
        node.name = data.get("name", "")
        node.visible = bool(data.get("visible", True))
        node.locked = bool(data.get("locked", False))
        node.parent_slot = data.get("parent_slot")
        node.group_id = data.get("group_id")
        node.description = data.get("description", "")
        raw_meta = data.get(_CTKMETA_KEY)
        if isinstance(raw_meta, dict):
            node.extra = dict(raw_meta)
        # Old ``.ctkproj`` files may carry legacy handler shapes:
        # bare method-name strings (page methods), ``ref_call`` dicts
        # (Object References), or ``library_call`` dicts (library
        # scripts). The CTkScript model keeps NONE of them — only
        # ``script_call`` dict entries survive; everything else is
        # dropped on load (clean break) so old projects open clean.
        raw_handlers = data.get("handlers")
        if isinstance(raw_handlers, dict):
            normalised: dict[str, list] = {}
            for k, v in raw_handlers.items():
                if not isinstance(v, list):
                    continue
                # Keep only ``script_call`` entries (see above).
                entries = [
                    copy.deepcopy(raw)
                    for raw in v
                    if isinstance(raw, dict)
                    and raw.get("kind") == "script_call"
                ]
                if entries:
                    normalised[str(k)] = entries
            node.handlers = normalised
        raw_components = data.get("attached_components")
        if isinstance(raw_components, list):
            node.attached_components = [
                c for c in map(clean_component_dict, raw_components)
                if c is not None
            ]
        for child_data in data.get("children", []):
            child = cls.from_dict(child_data)
            child.parent = node
            node.children.append(child)
        return node
