> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-04-22 · modified: 2026-04-22 · archived: 2026-07-31

# Plugin Structure Homogenisation — Design Spec

**Date:** 2026-04-16
**Status:** Draft
**Prerequisite:** `rosy-seeking-bunny.md` plan complete (sectionplot/customplot decomposition + Matplotlib API fixes)

---

## Context

`midvatten_plugin.py` has grown to 1,693 lines. The growth is almost entirely mechanical: each of the ~40 plugin actions has its own handler method that repeats the same pattern — precondition checks, instantiate a tool class, call show. Precondition logic (which layers must not be in edit mode, whether a selection is required) is expressed as scattered imperative calls rather than declared facts.

At the same time, tool classes have no shared interface contract: constructors accept different argument signatures (`(iface.mainWindow(), iface)`, `(iface.mainWindow(), ms)`, `(activeLayer, ms.settingsdict)`, `(ms, activeLayer)`, …) and expose no consistent entry point. This means the plugin handler must know each tool's internal expectations.

The result is a plugin that is hard to extend (adding a tool means adding a handler method, knowing which utility calls to make, in which order) and hard to read (the full feature list is not visible in one place).

This plan homogenises the structure so that:
- The plugin is a thin orchestrator with a declarative manifest
- Every tool is self-contained with a uniform interface
- Preconditions are declared, not scattered
- The plugin file shrinks from ~1,693 lines to ~400 lines

---

## Design

### 1. ActionSpec manifest

A `dataclass` declared at module level in `midvatten_plugin.py` (after imports, before the `Midvatten` class):

```python
@dataclass
class ActionSpec:
    id: str                                  # unique key; also used as persistent-tool dict key
    label: str                               # shown in menu and toolbar tooltip
    icon: str                                # filename in icons/
    menu: str                                # "import" | "export" | "edit" | "plot" | "report" | "db" | "utils"
    tool_class: type | None = None           # class to instantiate; None → use callback
    callback: Callable[[], None] | None = None  # for trivial direct calls with no tool class
    needs_db: bool = True                    # check DB + settings loaded before running
    critical_layers: tuple[str, ...] = ()   # layers that must not be in edit mode
    needs_selection: bool = False            # active layer must have ≥1 selected features
    needs_active_layer: str | None = None   # specific layer must be active and not in edit mode
    persistent: bool = False                 # reuse window instead of re-creating each call
```

A single module-level list `_ACTIONS: list[ActionSpec]` replaces all ~40 handler methods as the authoritative description of what the plugin does. The full feature list is readable at a glance.

**Known layer names** for `critical_layers` (from audit):
`obs_points`, `obs_lines`, `w_levels`, `w_levels_logger`, `w_qual_lab`, `w_qual_field`,
`w_flow`, `stratigraphy`, `comments`, `zz_flowtype`

### 2. Uniform tool interface

**Constructor:** `Tool.__init__(self, iface, ms)` for all tool classes.
- `iface` — the QGIS interface object; provides `iface.mainWindow()`, `iface.activeLayer()`, etc.
- `ms` — `MidvSettings` instance; provides `ms.settingsdict` and DB settings.
- Constructor must be cheap: no dialogs, no DB queries.

**Entry point:** `Tool.show(self) -> None` for all tool classes.
- Tools that are modal dialogs call `self.exec()` inside their own `show()`.
- Tools that need settings validation, geometry checks, or "are you sure?" confirmations perform those inside `show()` before showing the UI.
- The dispatcher always calls `tool.show()`.

This is a change to ~25 tool classes. For most, it is mechanical: rename arguments in `__init__`, extract what the tool needs from `iface`/`ms`, and ensure a `show()` method exists.

### 3. The dispatcher

Replaces all ~40 handler methods in `Midvatten`. One method, called for every action:

```python
@general_exception_handler
@waiting_cursor
def _dispatch(self, spec: ActionSpec) -> None:
    # Preconditions
    if spec.needs_db:
        # verify_msettings_loaded_and_layer_edit_mode returns a non-zero err_flag on failure
        err_flag = verify_msettings_loaded_and_layer_edit_mode(
            self.iface, self.ms, spec.critical_layers
        )
        if err_flag:
            return
    if spec.needs_selection:
        if not verify_layer_selection():
            return
    if spec.needs_active_layer:
        if not verify_this_layer_selected_and_not_in_edit_mode(spec.needs_active_layer):
            return

    # Persistent window reuse
    if spec.persistent:
        existing = self._open_tools.get(spec.id)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

    # Run
    if spec.callback:
        spec.callback()
        return
    tool = spec.tool_class(self.iface, self.ms)
    tool.show()
    if spec.persistent:
        self._open_tools[spec.id] = tool
```

`self._open_tools: dict[str, QWidget]` is initialised as `{}` in `__init__`.

### 4. Exception handling and waiting cursor

**Two-layer strategy:**

- The dispatcher is decorated with `@general_exception_handler` and `@waiting_cursor`. This guarantees the cursor is always restored and uncaught exceptions always reach the log, for every action in the plugin, with no per-tool boilerplate.
- Tools handle their own domain errors explicitly: catch specific exceptions, emit a user-readable `MessagebarAndLog` message, return. Do not use bare `except Exception` inside tools.
- Anything a tool does not handle propagates to the dispatcher's top-level catcher as a last resort.

### 5. Menu and toolbar construction

`Midvatten.initGui()` loops over `_ACTIONS` to build menus and toolbar entries. The construction logic currently split between `initGui`, `_create_actions`, `_build_menus`, `_build_toolbar`, and `_connect_signals` collapses into a loop over the manifest. `tool_registry.py` is deleted; its `add_plugin_action` helper is either inlined or replaced by the loop.

### 6. ExportSpatialite extraction

The `export_spatialite()` handler in `midvatten_plugin.py` is currently ~90 lines of inline workflow code. It is extracted into a new class `ExportSpatialite` in `tools/export_spatialite.py` with the standard `__init__(iface, ms)` / `show()` interface. The current dialog sequence and behavior are preserved exactly — no UX changes in this plan.

This gives `export_spatialite` an entry in `_ACTIONS` like any other tool.

---

## Files

### Modified
| File | Change |
|------|--------|
| `midvatten_plugin.py` | Replace ~40 handler methods with `_ACTIONS` list + `_dispatch()`; update `initGui()` to loop over manifest |
| All ~25 tool classes in `tools/` | Standardise `__init__(iface, ms)` + `show()` interface |

### New
| File | Purpose |
|------|---------|
| `tools/export_spatialite.py` | `ExportSpatialite` class extracted from plugin handler (same behavior) |

### Deleted
| File | Reason |
|------|--------|
| `tool_registry.py` | Folded into `initGui()` loop |

---

## Implementation notes

- **Build in a git worktree** — this is a broad change touching many files; isolation is important.
- **Use subagents** to conserve main-thread context; each phase can be a separate agent task.
- **Write integration tests before changes** for any behavior that could break: precondition checking logic, persistent window reuse, the dispatcher itself. Use the existing test infrastructure (`@pytest.mark.spatialite`, mock `MessagebarAndLog`).

### Suggested phases

**Phase 1 — Tool interface standardisation** (mechanical, lowest risk)
Standardise `__init__(iface, ms)` + `show()` across all tool classes. Run full test suite after each file. No changes to `midvatten_plugin.py` yet.

**Phase 2 — ActionSpec manifest + dispatcher**
Write `_ACTIONS` list and `_dispatch()`. Wire up `initGui()` to loop over the manifest. Delete `tool_registry.py`. Verify the full plugin still operates correctly.

**Phase 3 — ExportSpatialite extraction**
Extract `export_spatialite()` handler into `tools/export_spatialite.py`. Add its entry to `_ACTIONS`. Verify behavior matches current implementation.

---

## Verification

- Full test suite passes after each phase (`python3 -m pytest test/ -x`)
- Manual smoke test: open plugin in QGIS, trigger one action from each menu category
- `midvatten_plugin.py` line count is below 500 after Phase 2
- No new `except Exception` bare catches introduced in tool classes
- `tool_registry.py` is absent from the repo after Phase 2
