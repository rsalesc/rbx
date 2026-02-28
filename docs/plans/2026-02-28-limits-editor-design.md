# Limits Editor UI Design

## Goal

Add a Limits Editor screen to `rbx ui` for viewing and editing limits profiles (`.limits/*.yml`). Profiles control time/memory limits used by `rbx run`, `rbx time`, and statement generation.

## Layout

Left sidebar (`ListView`) with profile names + "+ New Profile" entry. Right panel is a scrollable form for the selected profile.

```
┌──────────────┬──────────────────────────────────────┐
│ Profiles     │  Limits Editor: "local"              │
│              │                                      │
│ > local      │  Inherit from package: [ ] No        │
│   judge      │                                      │
│              │  ── Global Limits ──                  │
│   + New      │  Time Limit (ms):  [  2000  ]        │
│              │  Memory Limit (MB):[  256   ]         │
│              │                                      │
│              │  ── Per-Language Overrides ──         │
│              │  cpp:                                │
│              │    Time (ms):       [  1500  ]        │
│              │    Time Multiplier: [       ]         │
│              │    Memory (MB):     [       ]         │
│              │                                      │
│              │  [+ Add Language]  [Save (Ctrl+S)]    │
└──────────────┴──────────────────────────────────────┘
```

## Behavior

### Profile selection
- Sidebar lists profiles from `.limits/*.yml` plus "+ New Profile"
- Selecting a profile loads its **raw** (unexpanded) data into the form
- "+ New Profile" prompts for a name, creates an empty profile
- Delete profile via keybinding (`d`/`delete`) with confirmation

### Inherit toggle
- ON: global limits and per-language sections show package limits read-only
- OFF: form inputs become editable, package values shown as placeholders

### Per-language modifiers
- Languages from `environment.get_environment().languages` shown by default
- "+ Add Language" allows typing a custom language key
- Each language row: Time (ms), Time Multiplier, Memory (MB) -- all optional
- Empty fields = no override (excluded from YAML)

### Saving
- `ctrl+s` or Save button writes to `.limits/{profile}.yml`
- Uses `utils.model_to_yaml()` on a constructed `LimitsProfile`
- Brief notification confirms save

### Validation
- TL/ML: positive integers or empty
- Time multiplier: positive float or empty
- Invalid values show inline error styling

## Data flow

1. Load profile names: `limits_info.get_available_profile_names()`
2. Load raw profile: `limits_info.get_saved_limits_profile(name)`
3. Package limits: `package.find_problem_package_or_die()` for inherit display and placeholders
4. Languages: `environment.get_environment().languages`
5. Save: construct `LimitsProfile` from form, serialize, write to `package.get_limits_file(profile)`

## Files

- **New:** `rbx/box/ui/screens/limits_editor.py`
- **Modified:** `rbx/box/ui/css/app.tcss` (new screen styles)
- **Modified:** `rbx/box/ui/main.py` (add menu entry)

## Widgets

`Input` (numeric fields), `Switch` (inherit toggle), `Button` (save, add language), `ListView` (sidebar), `Label`/`Static` (headers, read-only), `VerticalScroll` (right panel)
