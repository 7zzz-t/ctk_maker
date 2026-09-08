import copy
import uuid

# Backwards-compat widget type renames. Older ``.ctkproj`` files
# stored the historical type name; on load we silently translate to
# the current one so existing projects don't break after a rename.
# Rename only — kwargs / properties are unchanged across these mappings.
_WIDGET_TYPE_RENAMES = {
    "Shape": "Card",  # 2026-04-27: Shape → Card
}

# Builder-only disk carriers for 02 features stock CTkMaker (00) can't
# express. In-memory, a CTkFrame ``height == 0`` means "auto-height"
# (content-sized container); stock 00 renders 0-height frames as
# invisible, so on disk we write a visible snapshot height plus a
# marker. The marker MUST live at the widget's TOP level, NOT inside
# ``properties``: stock 00 hands every ``properties`` key to the CTk
# constructor (``create_widget``), so an unknown property key crashes
# with "not supported arguments". Unknown top-level keys are ignored by
# 00's loader (it only reads keys it knows); 00's saver drops them on
# the next save, which degrades the file to the fixed snapshot height.
_CTKFRAME_AUTO_HEIGHT_KEY = "_ctkmaker_auto_height"
_CTKFRAME_AUTO_HEIGHT_SNAPSHOT = 200
# Single top-level carrier for ALL 02 builder-only enhancement params
# (see docs/LAYOUT_ENHANCEMENT_COMPAT.md §11). Kept out of
# ``properties`` for the same reason as the auto-height marker: stock
# 00 forwards every property key to the CTk constructor.
_CTKMETA_KEY = "_ctkmaker_meta"


def _bake_pack_child_disk(container, child, child_dict):
    """Spec §11.5 disk bake: percent / remainder children of a
    fixed-axis pack container serialize as stock 00 parameters —
    ``stretch="fill"`` (cross axis stretches, main axis pinned) plus the
    exact main-axis px — so stock 00 renders the layout pixel-identical
    to the 02 canvas. The in-memory ``extra`` keeps the responsive
    semantics (02 preview and the exported .py still re-derive grow /
    px at runtime). Returns ``child_dict`` (possibly rewritten)."""
    if child is None or not isinstance(child_dict, dict):
        return child_dict
    parent_props = (container.properties or {}) if container is not None else {}
    layout = parent_props.get("layout_type")
    axis = None
    if layout == "vbox":
        axis = "height"
    elif layout == "hbox":
        axis = "width"
    if axis is None:
        return child_dict
    try:
        parent_px = int(parent_props.get(axis, 0) or 0)
    except (TypeError, ValueError):
        return child_dict
    if parent_px <= 0:
        return child_dict
    if getattr(container, "widget_type", "") == "CTkScrollableFrame":
        return child_dict
    if (container.extra or {}).get("height_mode") == "auto":
        return child_dict
    try:
        if int(parent_props.get("height", 0) or 0) <= 0:
            return child_dict
    except (TypeError, ValueError):
        return child_dict

    child_extra = child.extra or {}
    bucket = child_extra.get("main_axis")
    mode = (bucket or {}).get("mode") if isinstance(bucket, dict) else None
    if mode not in ("percent", "remain"):
        return child_dict

    def _sib_mode(sib):
        b = (sib.extra or {}).get("main_axis")
        m = (b or {}).get("mode") if isinstance(b, dict) else None
        if m == "percent":
            return "percent"
        if m == "remain":
            return "grow"  # remainder children share the grow pool
        return "grow" if str(sib.properties.get("stretch", "")) == "grow" \
            else "fixed"

    def _pct_px(sib, p_px):
        b = (sib.extra or {}).get("main_axis")
        try:
            pct = int((b or {}).get("percent", 50))
        except (TypeError, ValueError):
            pct = 50
        pct = max(1, min(100, pct))
        return max(1, round(p_px * pct / 100))

    siblings = list(getattr(container, "children", None) or [])
    try:
        spacing = int(parent_props.get("layout_spacing", 0) or 0)
    except (TypeError, ValueError):
        spacing = 0
    fixed_total = 0
    grow_count = 0
    for sib in siblings:
        m = _sib_mode(sib)
        if m == "percent":
            fixed_total += _pct_px(sib, parent_px)
        elif m == "grow":
            grow_count += 1
        else:
            try:
                fixed_total += max(0, int(sib.properties.get(axis, 0) or 0))
            except (TypeError, ValueError):
                pass

    if mode == "percent":
        baked_px = _pct_px(child, parent_px)
    else:
        spacing_total = spacing * max(0, len(siblings) - 1)
        avail = max(0, parent_px - fixed_total - spacing_total)
        baked_px = max(1, avail // max(1, grow_count))

    props = dict(child_dict.get("properties") or {})
    props[axis] = baked_px
    props["stretch"] = "fill"
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
        disk_auto = (
            self.widget_type == "CTkFrame"
            and props.get("height") == 0
        )
        if disk_auto:
            # In-memory 0 = auto-height (content-sized). Disk carries a
            # visible snapshot height (properties must stay CTk-safe —
            # stock 00 forwards every property key to the constructor)
            # plus a top-level marker (see module docstring).
            props["height"] = _CTKFRAME_AUTO_HEIGHT_SNAPSHOT
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
        if disk_auto:
            result[_CTKFRAME_AUTO_HEIGHT_KEY] = True
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
        raw_props = data.get("properties", {})
        if (
            widget_type == "CTkFrame"
            and data.get(_CTKFRAME_AUTO_HEIGHT_KEY)
        ):
            # Disk snapshot + top-level marker → in-memory auto (0).
            raw_props = dict(raw_props)
            raw_props["height"] = 0
        node = cls(
            widget_type=widget_type,
            properties=raw_props,
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
