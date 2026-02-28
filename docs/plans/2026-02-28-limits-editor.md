# Limits Editor UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Limits Editor screen to `rbx ui` for viewing, creating, and editing limits profiles (`.limits/*.yml`).

**Architecture:** New `LimitsEditorScreen` added as third option in the main `rbxApp` menu. Left sidebar `ListView` lists profiles + "New" entry. Right panel is a scrollable form with `Switch` (inherit toggle), `Input` fields (TL, ML, per-language modifiers), and Save button. Data flows from `.limits/*.yml` files through `limits_info` helpers, and saves back via `utils.model_to_yaml()`.

**Tech Stack:** Textual (>=8.0), Pydantic v2 (`LimitsProfile`, `LimitModifiers`), `rbx.box.limits_info`, `rbx.box.environment`

---

### Task 1: Create the LimitsEditorScreen skeleton with sidebar

**Files:**
- Create: `rbx/box/ui/screens/limits_editor.py`
- Modify: `rbx/box/ui/main.py:17-20` (add menu entry)
- Modify: `rbx/box/ui/css/app.tcss` (add styles)

**Step 1: Create the screen file with sidebar and empty detail pane**

Create `rbx/box/ui/screens/limits_editor.py`:

```python
import pathlib
from typing import Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from rbx.box import limits_info, package
from rbx.box.schema import LimitsProfile


class LimitsEditorScreen(Screen):
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
    ]

    def __init__(self):
        super().__init__()
        self._profile_names: List[str] = []
        self._selected_profile: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='limits-editor'):
            with Vertical(id='limits-sidebar'):
                yield ListView(id='limits-profile-list')
            with VerticalScroll(id='limits-detail'):
                yield Static('Select a profile', id='limits-placeholder')

    async def on_mount(self):
        self.query_one('#limits-profile-list').border_title = 'Profiles'
        await self._load_profiles()
        self.watch(
            self.query_one('#limits-profile-list', ListView),
            'index',
            self._on_profile_selected,
        )

    async def _load_profiles(self):
        self._profile_names = limits_info.get_available_profile_names()
        lv = self.query_one('#limits-profile-list', ListView)
        await lv.clear()
        items = [ListItem(Label(name)) for name in self._profile_names]
        items.append(ListItem(Label('[dim]+ New Profile[/dim]', markup=True)))
        await lv.extend(items)

    def _on_profile_selected(self, index: Optional[int]):
        if index is None:
            return
        if index == len(self._profile_names):
            # "+ New Profile" selected - will be handled in Task 4
            return
        self._selected_profile = self._profile_names[index]
```

**Step 2: Add the menu entry in main.py**

In `rbx/box/ui/main.py`, add the import (line 15 area) and extend `SCREEN_OPTIONS` (line 17-20):

```python
# Add import:
from rbx.box.ui.screens.limits_editor import LimitsEditorScreen

# Extend SCREEN_OPTIONS:
SCREEN_OPTIONS = [
    ('Explore tests built by `rbx build`.', TestExplorerScreen),
    ('Explore results of a past `rbx run`.', RunExplorerScreen),
    ('Edit limits profiles.', LimitsEditorScreen),
]
```

**Step 3: Add CSS for the new screen**

Append to `rbx/box/ui/css/app.tcss`:

```css
LimitsEditorScreen {
    #limits-sidebar {
        min-width: 20;
        max-width: 30;
        height: 1fr;
    }
    #limits-profile-list {
        width: 1fr;
    }
    #limits-detail {
        height: 1fr;
        padding: 1 2;
    }
}
```

**Step 4: Verify it runs**

Run: `uv run rbx ui` inside a problem directory. Verify:
- Third menu option "Edit limits profiles." appears
- Selecting it pushes the screen with sidebar listing profile names
- `q` returns to main menu

**Step 5: Commit**

```
feat(ui): add limits editor screen skeleton with profile sidebar
```

---

### Task 2: Build the profile detail form (inherit toggle + global limits)

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py`
- Modify: `rbx/box/ui/css/app.tcss`

**Step 1: Add the form widgets to the detail pane**

Replace the placeholder `Static` with a proper form. Update `LimitsEditorScreen` to dynamically compose the detail pane when a profile is selected. Use `Switch` for inherit toggle and `Input` for TL/ML.

Add these imports to `limits_editor.py`:

```python
from textual.widgets import Button, Input, Switch, Rule
```

Add a method `_build_detail_form` that removes the current detail content and mounts form widgets:

```python
async def _load_profile_detail(self):
    """Load the selected profile data into the form."""
    detail = self.query_one('#limits-detail', VerticalScroll)
    await detail.remove_children()

    if self._selected_profile is None:
        await detail.mount(Static('Select a profile', id='limits-placeholder'))
        return

    raw_profile = limits_info.get_saved_limits_profile(self._selected_profile)
    if raw_profile is None:
        raw_profile = LimitsProfile()

    pkg = package.find_problem_package_or_die()

    # Title
    await detail.mount(
        Static(f'[b]Profile: {self._selected_profile}[/b]', markup=True, id='limits-title')
    )

    # Inherit toggle
    await detail.mount(Static('Inherit from package:', id='inherit-label'))
    inherit_switch = Switch(value=raw_profile.inheritFromPackage, id='inherit-switch')
    await detail.mount(inherit_switch)

    await detail.mount(Rule())

    # Global limits section
    await detail.mount(Static('[b]Global Limits[/b]', markup=True, id='global-limits-header'))

    tl_value = str(raw_profile.timeLimit) if raw_profile.timeLimit is not None else ''
    tl_placeholder = str(pkg.timeLimit)
    await detail.mount(Static('Time Limit (ms):'))
    await detail.mount(Input(value=tl_value, placeholder=tl_placeholder, id='input-tl', type='integer'))

    ml_value = str(raw_profile.memoryLimit) if raw_profile.memoryLimit is not None else ''
    ml_placeholder = str(pkg.memoryLimit)
    await detail.mount(Static('Memory Limit (MB):'))
    await detail.mount(Input(value=ml_value, placeholder=ml_placeholder, id='input-ml', type='integer'))
```

Update `_on_profile_selected` to call `_load_profile_detail`:

```python
def _on_profile_selected(self, index: Optional[int]):
    if index is None:
        return
    if index == len(self._profile_names):
        return
    self._selected_profile = self._profile_names[index]
    self._load_profile_detail()
```

**Step 2: Handle inherit toggle to disable/enable inputs**

Add a watcher for the switch. When inherit is ON, disable the global limit inputs and show package values read-only:

```python
def on_switch_changed(self, event: Switch.Changed) -> None:
    if event.switch.id == 'inherit-switch':
        is_inherited = event.value
        tl_input = self.query_one('#input-tl', Input)
        ml_input = self.query_one('#input-ml', Input)
        tl_input.disabled = is_inherited
        ml_input.disabled = is_inherited
```

**Step 3: Add CSS for form styling**

Append to the `LimitsEditorScreen` CSS block:

```css
LimitsEditorScreen {
    /* ... existing sidebar styles ... */
    #limits-title {
        text-style: bold;
        margin-bottom: 1;
    }
    Switch {
        margin-bottom: 1;
        height: auto;
    }
    #limits-detail Input {
        margin-bottom: 1;
    }
    #limits-detail Static {
        height: auto;
    }
    #limits-detail Rule {
        margin: 1 0;
    }
}
```

**Step 4: Verify the form renders**

Run `uv run rbx ui` in a problem with existing profiles. Selecting a profile should show the inherit toggle and TL/ML inputs. Toggling inherit should disable/enable the inputs.

**Step 5: Commit**

```
feat(ui): add profile detail form with inherit toggle and global limits
```

---

### Task 3: Add per-language modifier editing

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py`
- Modify: `rbx/box/ui/css/app.tcss`

**Step 1: Add per-language modifier section to the form**

After the global limits, add a section for per-language modifiers. Load languages from the environment and show existing modifiers.

Add import:
```python
from rbx.box import environment
from rbx.box.schema import LimitModifiers
```

Add to `_load_profile_detail`, after the global limits section:

```python
    await detail.mount(Rule())
    await detail.mount(Static('[b]Per-Language Overrides[/b]', markup=True))

    # Get languages from environment
    env = environment.get_environment()
    env_language_names = [lang.name for lang in env.languages]

    # Merge with any languages already in the profile modifiers
    all_languages = list(dict.fromkeys(env_language_names + list(raw_profile.modifiers.keys())))

    self._modifier_languages = all_languages

    for lang in all_languages:
        modifier = raw_profile.modifiers.get(lang, LimitModifiers())
        readable = lang
        for env_lang in env.languages:
            if env_lang.name == lang:
                readable = env_lang.readableName or lang
                break

        await detail.mount(Static(f'[bold]{readable}[/bold] ({lang}):', markup=True))

        time_val = str(modifier.time) if modifier.time is not None else ''
        await detail.mount(Static('  Time (ms):'))
        await detail.mount(Input(value=time_val, placeholder='', id=f'mod-time-{lang}', type='integer'))

        mult_val = str(modifier.timeMultiplier) if modifier.timeMultiplier is not None else ''
        await detail.mount(Static('  Time Multiplier:'))
        await detail.mount(Input(value=mult_val, placeholder='', id=f'mod-mult-{lang}', type='number'))

        mem_val = str(modifier.memory) if modifier.memory is not None else ''
        await detail.mount(Static('  Memory (MB):'))
        await detail.mount(Input(value=mem_val, placeholder='', id=f'mod-mem-{lang}', type='integer'))
```

Also update the inherit toggle handler to disable per-language inputs:

```python
def on_switch_changed(self, event: Switch.Changed) -> None:
    if event.switch.id == 'inherit-switch':
        is_inherited = event.value
        # Disable all inputs in the detail pane
        for inp in self.query_one('#limits-detail').query(Input):
            inp.disabled = is_inherited
```

**Step 2: Verify per-language section renders**

Run `uv run rbx ui`, select a profile. Verify language rows appear with correct pre-filled values. Toggling inherit should disable all inputs.

**Step 3: Commit**

```
feat(ui): add per-language modifier editing to limits editor
```

---

### Task 4: Add Save functionality

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py`

**Step 1: Add save button and ctrl+s binding**

Add save button at the end of the form in `_load_profile_detail`:

```python
    await detail.mount(Rule())
    await detail.mount(Button('Save (Ctrl+S)', id='save-btn', variant='primary'))
```

Add binding:
```python
BINDINGS = [
    ('q', 'app.pop_screen', 'Quit'),
    ('ctrl+s', 'save_profile', 'Save'),
]
```

**Step 2: Implement the save action**

Add the `_build_profile_from_form` and `action_save_profile` methods:

```python
def _build_profile_from_form(self) -> LimitsProfile:
    """Construct a LimitsProfile from the current form state."""
    inherit = self.query_one('#inherit-switch', Switch).value

    if inherit:
        return LimitsProfile(inheritFromPackage=True)

    tl_str = self.query_one('#input-tl', Input).value.strip()
    ml_str = self.query_one('#input-ml', Input).value.strip()

    time_limit = int(tl_str) if tl_str else None
    memory_limit = int(ml_str) if ml_str else None

    modifiers: Dict[str, LimitModifiers] = {}
    for lang in self._modifier_languages:
        time_str = self.query_one(f'#mod-time-{lang}', Input).value.strip()
        mult_str = self.query_one(f'#mod-mult-{lang}', Input).value.strip()
        mem_str = self.query_one(f'#mod-mem-{lang}', Input).value.strip()

        time_val = int(time_str) if time_str else None
        mult_val = float(mult_str) if mult_str else None
        mem_val = int(mem_str) if mem_str else None

        if time_val is not None or mult_val is not None or mem_val is not None:
            modifiers[lang] = LimitModifiers(
                time=time_val,
                timeMultiplier=mult_val,
                memory=mem_val,
            )

    return LimitsProfile(
        inheritFromPackage=False,
        timeLimit=time_limit,
        memoryLimit=memory_limit,
        modifiers=modifiers,
    )

async def action_save_profile(self) -> None:
    if self._selected_profile is None:
        self.app.notify('No profile selected', severity='error')
        return

    try:
        profile = self._build_profile_from_form()
    except (ValueError, TypeError) as e:
        self.app.notify(f'Invalid input: {e}', severity='error')
        return

    limits_path = package.get_limits_file(self._selected_profile)
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(utils.model_to_yaml(profile))

    self.app.notify(f'Saved profile "{self._selected_profile}"', severity='information')
```

Add the `utils` import:
```python
from rbx import utils
```

Wire up the button press:
```python
async def on_button_pressed(self, event: Button.Pressed) -> None:
    if event.button.id == 'save-btn':
        await self.action_save_profile()
```

**Step 3: Verify save works**

Run `uv run rbx ui`, select a profile, modify a value, press Ctrl+S. Check that `.limits/{profile}.yml` is updated. Re-select the profile to confirm values persist.

**Step 4: Commit**

```
feat(ui): add save functionality to limits editor
```

---

### Task 5: Add "New Profile" and "Delete Profile" support

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py`

**Step 1: Implement new profile creation**

When the user selects "+ New Profile", show an `Input` for the profile name. On submit, create an empty profile and refresh the list.

Add to `_on_profile_selected`:

```python
def _on_profile_selected(self, index: Optional[int]):
    if index is None:
        return
    if index == len(self._profile_names):
        self._show_new_profile_input()
        return
    self._selected_profile = self._profile_names[index]
    self._load_profile_detail()

async def _show_new_profile_input(self):
    detail = self.query_one('#limits-detail', VerticalScroll)
    await detail.remove_children()
    await detail.mount(Static('Enter new profile name:'))
    await detail.mount(Input(placeholder='e.g. local, judge', id='new-profile-name'))

async def on_input_submitted(self, event: Input.Submitted) -> None:
    if event.input.id == 'new-profile-name':
        name = event.value.strip()
        if not name:
            self.app.notify('Profile name cannot be empty', severity='error')
            return
        if name in self._profile_names:
            self.app.notify(f'Profile "{name}" already exists', severity='error')
            return
        # Create empty profile file
        limits_path = package.get_limits_file(name)
        limits_path.parent.mkdir(parents=True, exist_ok=True)
        limits_path.write_text(utils.model_to_yaml(LimitsProfile()))
        self._selected_profile = name
        await self._load_profiles()
        # Select the new profile in the list
        new_index = self._profile_names.index(name)
        self.query_one('#limits-profile-list', ListView).index = new_index
        self._load_profile_detail()
```

**Step 2: Implement profile deletion**

Add delete binding and action:

```python
BINDINGS = [
    ('q', 'app.pop_screen', 'Quit'),
    ('ctrl+s', 'save_profile', 'Save'),
    ('d', 'delete_profile', 'Delete profile'),
]

async def action_delete_profile(self) -> None:
    if self._selected_profile is None:
        self.app.notify('No profile selected', severity='error')
        return
    limits_path = package.get_limits_file(self._selected_profile)
    if limits_path.exists():
        limits_path.unlink()
    self.app.notify(f'Deleted profile "{self._selected_profile}"', severity='information')
    self._selected_profile = None
    await self._load_profiles()
    detail = self.query_one('#limits-detail', VerticalScroll)
    await detail.remove_children()
    await detail.mount(Static('Select a profile', id='limits-placeholder'))
```

**Step 3: Verify new/delete work**

Run `uv run rbx ui`. Test:
- Select "+ New Profile", type a name, press Enter. Verify the profile appears in the sidebar and opens in the form.
- Select a profile, press `d`. Verify it's removed from the sidebar and the `.limits/` directory.

**Step 4: Commit**

```
feat(ui): add new profile creation and deletion to limits editor
```

---

### Task 6: Add custom language support

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py`

**Step 1: Add "Add Language" button and input**

After the per-language modifier rows, add a button. When clicked, show an input for the language key. On submit, add a new modifier row.

In `_load_profile_detail`, after the language loop:

```python
    await detail.mount(Button('+ Add Language', id='add-lang-btn', variant='default'))
```

Handle the button press:

```python
async def on_button_pressed(self, event: Button.Pressed) -> None:
    if event.button.id == 'save-btn':
        await self.action_save_profile()
    elif event.button.id == 'add-lang-btn':
        await self._show_add_language_input()

async def _show_add_language_input(self):
    detail = self.query_one('#limits-detail', VerticalScroll)
    # Remove existing add-language input if present
    for widget in detail.query('#add-lang-input'):
        await widget.remove()
    inp = Input(placeholder='Language key (e.g. cpp, java)', id='add-lang-input')
    # Mount before the add-lang-btn
    await detail.mount(inp, before=self.query_one('#add-lang-btn'))
    inp.focus()
```

Handle submission of the language input:

```python
async def on_input_submitted(self, event: Input.Submitted) -> None:
    if event.input.id == 'new-profile-name':
        # ... existing handler ...
    elif event.input.id == 'add-lang-input':
        lang = event.value.strip()
        if not lang:
            return
        if lang in self._modifier_languages:
            self.app.notify(f'Language "{lang}" already exists', severity='error')
            return
        self._modifier_languages.append(lang)
        # Reload form preserving current state
        await self._reload_form_with_new_language(lang)
```

For simplicity, `_reload_form_with_new_language` should save current form state, add the language to `_modifier_languages`, and re-render the full form via `_load_profile_detail` — but using the form's current values instead of re-reading from disk. A pragmatic approach: just re-call `_load_profile_detail` after saving the current state to a temporary `LimitsProfile`:

```python
async def _reload_form_with_new_language(self, new_lang: str):
    """Save current form state and reload with new language added."""
    try:
        current = self._build_profile_from_form()
    except (ValueError, TypeError):
        current = LimitsProfile()
    # Temporarily save, reload detail
    self._pending_profile = current
    self._pending_profile.modifiers.setdefault(new_lang, LimitModifiers())
    await self._load_profile_detail_from(self._pending_profile)
```

This requires a small refactor: extract a `_load_profile_detail_from(profile)` method that takes a `LimitsProfile` directly, and have `_load_profile_detail` call it after loading from disk.

**Step 2: Verify adding a custom language**

Run `uv run rbx ui`, select a profile, click "+ Add Language", type "kotlin", press Enter. Verify a new kotlin modifier row appears. Save and verify the YAML contains the kotlin modifier.

**Step 3: Commit**

```
feat(ui): add custom language support to limits editor
```

---

### Task 7: Polish and edge cases

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py`
- Modify: `rbx/box/ui/css/app.tcss`

**Step 1: Show package limits when inheriting**

When inherit is ON, instead of just disabling inputs, show the expanded package limits as read-only text so the user sees what they're inheriting:

In the `on_switch_changed` handler, when inherit is toggled ON, call `_load_profile_detail` to re-render (it will display read-only package values). When toggled OFF, re-render with editable fields.

**Step 2: Input validation styling**

Add validation feedback: if the user types a non-numeric value in a TL/ML field, use Textual's built-in `Input` validation (`type='integer'` already handles this for Textual >=0.40). Verify `type='integer'` is supported in Textual 8.0.

**Step 3: Prevent accidental deletion**

Before deleting, show a confirmation. Use `self.app.push_screen` with a simple yes/no modal, or just `self.app.notify` with a double-press pattern (e.g., track `_delete_requested` flag).

**Step 4: Final CSS polish**

Ensure consistent spacing, proper border styling matching the rest of the app. Test in both light and dark terminal themes.

**Step 5: Verify everything works end to end**

Full test scenario:
1. `rbx ui` -> "Edit limits profiles."
2. Select existing profile -> verify TL/ML/modifiers load correctly
3. Toggle inherit ON -> verify package values shown read-only
4. Toggle inherit OFF -> verify inputs are editable
5. Modify TL, add a per-language modifier
6. Ctrl+S -> verify saved to disk
7. "+ New Profile" -> create "test-profile" -> verify appears in sidebar
8. Delete "test-profile" -> verify removed
9. "q" -> verify returns to main menu

**Step 6: Commit**

```
feat(ui): polish limits editor with validation and confirmation
```
