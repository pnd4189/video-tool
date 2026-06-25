# Code Standards & Development Guidelines

## Language & Environment

- **Language:** Python 3.12+
- **Package manager:** pip (venv at `.venv/`)
- **Schema framework:** Pydantic 2.7+
- **External CLI:** FFmpeg 6.1+ (hard dependency)
- **Testing:** pytest 8.0+

---

## Python Style & Conventions

### Naming

| Item | Convention | Example |
|------|-----------|---------|
| Modules | snake_case | `audio_graph.py`, `music_loop.py` |
| Functions | snake_case | `build_audio_graph()`, `prepare_seamless_music()` |
| Classes | PascalCase | `JobSpec`, `Timeline`, `RenderExecutor` |
| Constants | UPPER_SNAKE_CASE | `ZOOM_AMPLITUDE`, `MAX_INLINE_SCENES` |
| Private functions | `_leading_underscore` | `_stage_music()`, `_build_sequence()` |
| Type hints | Required on public | `def run(job: JobSpec) -> Timeline:` |

### Code Structure

**Prefer small functions over large ones:**
- Public function ~20 lines (high-level orchestration)
- Private helper ~50 lines (implementation detail)
- Class method ~30 lines (self-contained logic)

**Comments explain WHY, not WHAT:**
```python
# Good (WHY)
# Sidechain keyed off voice to duck music when narrator speaks
sidechaincompress(key=voice_key, threshold=0.05, ratio=8)

# Bad (WHAT — obvious from code)
# Create sidechain compressor with voice as key
sidechaincompress(key=voice_key, threshold=0.05, ratio=8)
```

**No dead code:** Delete unused functions, don't comment out. No `_v2`, `_old`, or `_removed` copies.

### Error Handling

**At boundaries only** (user input, file I/O, external CLI):
```python
# Boundary: file read
try:
    with open(path) as f:
        return json.load(f)
except FileNotFoundError:
    raise ValidationError(f"Config not found: {path}")

# Internal: trust precondition
def sum_gains(timeline: Timeline) -> float:
    # Assume timeline.scenes is never None (validated upstream)
    return sum(s.gain_db for s in timeline.scenes)
```

**Typed exceptions:**
```python
from videotool.core.errors import ValidationError, RenderError, DependencyError

# Specific, actionable
raise ValidationError(f"Voice not found at {voice_path}. Check job.yaml 'inputs.voice'.")
```

---

## Pydantic Schema (Job Spec First)

**Single source of truth:** `src/videotool/core/job_spec.py`

All configuration flows from schema:

```python
from pydantic import BaseModel, Field

class AudioSpec(BaseModel):
    voice_gain_db: float = Field(default=0.0, ge=-20, le=20)
    music_gain_db: float = Field(default=-30.0, ge=-80, le=0)
    duck: bool = True
    normalize_lufs: Optional[float] = Field(default=-14.0, ge=-23, le=0)
    # ↑ Bounds, defaults, and types declared here
    # ↑ CLI + API read from this, not hardcoded elsewhere

class EnhanceSpec(BaseModel):
    tier: Literal['light', 'full'] = 'light'
    mood: Optional[Literal['clean', 'melancholy', 'cozy', 'horror', 'action']] = None
    atmosphere: bool = False
    particle_overlay: Optional[str] = None
    parallax: bool = False
    grain: Optional[bool] = None      # None = preset-driven
    glow: Optional[bool] = None
    flicker: Optional[bool] = None
```

**Validation in schema, not CLI:**
- Field bounds (ge/le)
- Enum values (Literal)
- Custom validators (model_validator)
- Optional vs required

**CLI reads schema to suggest defaults:**
```python
from videotool.core.job_spec import AudioSpec
help_text = f"Voice gain (default: {AudioSpec.model_fields['voice_gain_db'].default} dB)"
```

---

## Testing Strategy

### Test Organization

```
tests/
├── test_job_spec.py           # Schema validation
├── test_timeline.py           # Timeline building
├── test_audio_graph.py        # Audio chain construction
├── test_music_loop.py         # Music seamless loop
├── test_subtitles.py          # Subtitle alignment
├── test_storyboard.py         # Storyboard auto-gen
├── test_segmented_plans.py    # Render plan building
├── test_render_executor.py    # FFmpeg execution
└── fixtures/
    └── generated/
        ├── voice-3s.wav       # Synthetic (ffmpeg -f lavfi)
        ├── music-1s.flac      # Synthetic tone
        ├── scene-001.jpg      # Dummy image
        └── ...
```

### Test Philosophy

**YAGNI (You Ain't Gonna Need It):**
- No mocks/stubs unless truly isolating external calls (ffmpeg, disk I/O)
- Prefer real data: synthesize tones with ffmpeg, use dummy images
- Tests that pass are integration tests, not isolated unit tests
- If a test requires stubbing, consider redesigning the code

**Minimal fixtures:**
- Synthetic audio (ffmpeg -f lavfi sine=440:d=3)
- Tiny dummy images (ffmpeg -f lavfi color=... -frames:v 1)
- No large pre-recorded videos
- CI runs in <30s

### Coverage Target

- **Minimum:** 80% line coverage
- **Focus:** Critical paths (audio chain, timeline, music loop, subtitle alignment)
- **Not required:** Error paths (catch rare ffmpeg bugs), GUI state machine

### Running Tests

```bash
cd /home/dung/VIBE_CODING/video-tool
.venv/bin/python -m pytest -q
# Expected: 155+ pass

# With coverage
.venv/bin/python -m pytest --cov=src/videotool --cov-report=term-missing
```

---

## Commits & Git Workflow

### Conventional Commits

```
<type>(<scope>): <subject>

<body (optional)>
<footer (optional)>
```

**Types:**
- `feat:` New feature (user-visible)
- `fix:` Bug fix (broken behavior)
- `refactor:` Code restructure (no behavior change)
- `perf:` Performance improvement
- `test:` Add/fix tests
- `docs:` Documentation only
- `chore:` Deps, tooling (no feature/fix)

**Scope:** Module/area (optional but recommended)
- `feat(audio): add sidechain duck` ✓
- `fix(music-loop): prevent click at boundary` ✓
- `refactor: extract shared filter logic` (scope optional here)

**Subject:**
- Imperative mood ("add" not "added")
- Lowercase first letter
- No period at end
- ~50 chars max

**Example:**
```
feat(render): add mood FX filters (clean/melancholy/cozy/horror/action)

Implement 5 mood presets via filtergraph effects:
- clean: vignette only
- melancholy: grain + vignette
- cozy: warm color + glow
- horror: flicker + high contrast
- action: saturated color + contrast

Mood independent of tier; rides single full-tier re-encode.

Fixes GH-15
```

### No AI References in Commits

❌ `feat: AI agent suggests mood FX`
✓ `feat(render): add mood FX presets (5 filters)`

❌ `fix: Claude review feedback on error handling`
✓ `fix(validation): add typed exceptions at boundaries`

---

## Import Organization

```python
# 1. Standard library
import json
from pathlib import Path
from typing import Optional, List

# 2. Third-party (pydantic, etc.)
from pydantic import BaseModel, Field

# 3. Local (videotool)
from videotool.core.job_spec import JobSpec
from videotool.core.errors import ValidationError
from videotool.render.audio_graph import build_audio_graph
```

Use `from videotool.X import Y`, not `import videotool.X as X`.

---

## Public API Boundaries

**Public interfaces (stable):**
- `videotool.cli.main:app` (Typer CLI)
- `videotool.core.services:ServiceOrchestrator` (render, validate, package)
- `videotool.core.job_spec:JobSpec` (schema)
- `videotool.core.errors:*` (exception types)

**Internal (unstable, can change):**
- `videotool.render.commands` (FFmpeg command building)
- `videotool.ai.align_script` (subtitle alignment internals)
- Workspace helpers, temp file management

**Breaking changes to public API:**
- Document in [CLAUDE.md](../CLAUDE.md) "Confirmed decisions"
- Update schema version if needed (Pydantic can handle migration)
- Notify users (email, GitHub release notes)

---

## Linting & Formatting

### Code Style

```bash
# Format with black
.venv/bin/black src/ tests/

# Check with ruff (linter)
.venv/bin/ruff check src/ tests/

# Type check with mypy (optional, not required)
.venv/bin/mypy src/videotool --ignore-missing-imports
```

### No Auto-Fixes in Main Flow

- Formatting: developer responsibility (`black` locally before commit)
- Linting: developer responsibility (`ruff` locally before commit)
- Pre-commit hooks: optional (not enforced in CI)

---

## Dependencies & Extras

### Core (always installed)
- pydantic 2.7+
- typer 0.12+
- rich (console output)
- ffmpeg (external)

### Extras

```bash
# [ai] — Faster-Whisper for transcription
pip install -e .[ai]

# [parallax] — DepthAnything V2 for local parallax
pip install -e .[parallax]

# [dev] — pytest, black, ruff, mypy
pip install -e .[dev]

# [gui] — FastAPI for thin web interface (optional)
pip install -e .[gui]
```

**Why extras:** Users can avoid downloading large models (Whisper 1.5GB, DepthAnything 350MB) if not needed.

---

## Configuration & Defaults

**All configuration in job.yaml + schema, not env vars:**

```yaml
# Good: explicit, versioned, reproducible
project:
  title: "Bình Thiên Tập 123"
audio:
  music_gain_db: -30
  normalize_lufs: -14.0
enhance:
  mood: melancholy
```

**Env vars only for paths/secrets (not feature config):**
```bash
# OK: override model path
VIDEOTOOL_MODEL_DIR=./models videotool transcribe job.yaml

# NOT OK: feature flag via env
VIDEOTOOL_ENABLE_PARALLAX=true videotool render ...  ❌ Use job.yaml instead
```

---

## Performance Considerations

### Optimize for Clarity, Then Speed

1. **Clarity first:** Code readability > clever optimizations
2. **Profile before optimizing:** Don't guess; measure FFmpeg execution time (usually 95%+ of total)
3. **Parallelize where safe:** `batch` uses ProcessPoolExecutor, segmented render skips cached clips

### Known Bottlenecks

| Bottleneck | Time | Mitigation |
|------------|------|-----------|
| FFmpeg encode (libx264) | ~1h for 1h video | Hardware: CPU cores, SSD I/O |
| Whisper transcription (base) | ~1–2 min per hour | Cache model locally, first run only |
| DepthAnything depth (CPU) | ~1–2 min per still | Cache depth maps, offload to Colab |
| Subtitle alignment | <1s | Inline (no bottleneck) |
| Audio normalization | <10s | Single-pass loudnorm, not iterative |

**FFmpeg is ~99% of wall-clock time.** Don't over-optimize Python when the bottleneck is encode.

---

## File Organization Best Practices

### New Feature Workflow

1. **Add schema fields first** (`job_spec.py`)
   - Define all config options + defaults + bounds
   - Update docstrings

2. **Build core logic** (new module or existing)
   - Write functions accepting schema objects
   - Test with small fixtures
   - No CLI wiring yet

3. **Wire CLI** (update `cli/commands.py` or `storyboard_commands.py`)
   - Add Typer command or flag
   - Schema-driven help text

4. **Update docs** (CLAUDE.md, design-guidelines.md, etc.)
   - Explain feature, not implementation
   - Link to schema if config is complex

5. **Test + commit**
   - Run full test suite
   - Conventional commit message

### Refactoring Workflow

1. **Preserve behavior:** Refactoring = no new features
2. **Update tests if boundaries change** (inputs/outputs)
3. **Don't rename unrelated code** (scope creep)
4. **Single commit:** One refactoring per PR

---

## Documentation in Code

### Docstrings (Python 3.10+ style)

```python
def build_audio_graph(timeline: Timeline, job: JobSpec) -> str:
    """Build FFmpeg audio filtergraph for voice + music sidechain.
    
    Args:
        timeline: Timeline with scene durations and audio settings.
        job: JobSpec with audio config (voice_gain_db, music_gain_db, duck).
    
    Returns:
        FFmpeg audio filtergraph string (e.g., "[v]amix=inputs=2[aout]").
    
    Raises:
        ValidationError: If timeline or job is invalid.
    
    Details:
        - Voice is split into main + sidechain key
        - Music fed into sidechaincompress keyed off voice
        - Result mixed and normalized to -14 LUFS
        - If normalize_lufs is null, loudnorm step skipped
    """
```

### Type Hints (Required on Public APIs)

```python
# Public function: full type hints required
def run(job: JobSpec, workspace: Path) -> Timeline:
    ...

# Private helper: can be less strict (but still recommended)
def _stage_music(paths: list[str], duration_seconds: float) -> Path:
    ...
```

### Comments (Sparingly)

```python
# Explain WHY, not WHAT
# Sidechain ratio 8:1 strong duck; attack 5ms fast respond, release 400ms slow recovery
sidechaincompress(ratio=8, attack=5, release=400)

# Don't comment the obvious
total = sum(gains)  # Sum all gains  ❌ Remove this

# Exception: FFmpeg filter syntax is unintuitive, okay to document
ffmpeg_filter = "[0][1]acrossfade=d=2:curve1=tri:curve2=tri"  # 2s triangular crossfade
```

---

## Security & Validation

### Input Validation

**All untrusted input validated at boundaries:**

```python
from videotool.core.validation import validate_job_path

# CLI entry point (untrusted input)
@app.command()
def render(job_path: str):
    job = validate_job_path(job_path)  # Raises ValidationError if invalid
    # From here, job is trusted

# Internal function (trusts precondition)
def _apply_filters(job: JobSpec):
    # Assume job is already validated; no re-checking
```

### Path Safety

**No shell injection via paths:**

```python
# Good: use Path object, escape filter args
from pathlib import Path
subtitle_path = Path(job.inputs.subtitles).resolve()
ffmpeg_args.append(f"subtitles='{subtitle_path}'")  # FFmpeg filter escaping

# Bad: string interpolation without escaping
cmd = f"ffmpeg ... -vf subtitles={subtitle_path}"  # Vulnerable to spaces, quotes

# Worst: shell=True in subprocess
subprocess.run(f"ffmpeg {cmd}", shell=True)  # Never do this
```

**Relative paths must stay inside job folder:**

```python
# Validate particle_overlay is inside job folder (prevent breakout)
overlay_path = (job_dir / job.enhance.particle_overlay).resolve()
if not str(overlay_path).startswith(str(job_dir.resolve())):
    raise ValidationError(f"Overlay path escapes job folder: {overlay_path}")
```

---

## License & Attribution

**Source files:** Boilerplate header optional (not enforced in this project)

**Dependencies:** All reviewed for license compatibility (audio-story channel is personal use, no commercial redistribution risk)

**Asset credits:** `package/youtube.py` generates `license-report.md` from `asset-index.yaml` metadata

---

## Reference Standards

- **Python:** PEP 8 (style) + PEP 484 (type hints)
- **Commits:** Conventional Commits (commitlint-style)
- **Docs:** CommonMark (Markdown)
- **Schema:** Pydantic V2 (BaseModel patterns)

---

## Onboarding Checklist

New developer:

- [ ] Install variant 2 (full-tier): `pip install -e .[ai]`
- [ ] Run test suite: `.venv/bin/python -m pytest -q` (expect 155+ pass)
- [ ] Try small job: see [deployment-guide.md](./deployment-guide.md) "Step 2"
- [ ] Read [CLAUDE.md](../CLAUDE.md) workflow + pitfalls
- [ ] Read [system-architecture.md](./system-architecture.md) render flow
- [ ] Explore schema: `src/videotool/core/job_spec.py` (JobSpec class)
- [ ] Try a CLI command: `videotool init-job test-job --help`

---

## Common Pitfalls & How to Avoid Them

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Hard-coded constants | Motion/loudness wrong on new job | Move to schema defaults (job_spec.py) |
| Path escaping in FFmpeg | Subtitles fail if path has spaces | Use Path objects, escape filter args |
| Env var feature flags | `VIDEOTOOL_ENABLE_X=1` cargo cult | Use job.yaml schema field instead |
| Dead code commented out | Future dev confused by old code | Delete; git history has it |
| Mocked tests passing but code broken | Real FFmpeg fails | Prefer real data over stubs |
| Schema fields with no defaults | CLI help unclear | Use Field(default=...) + docstring |
| Validation only in CLI | API caller bypasses checks | Validate in services (before render) |

---

## Support & Review

- **Code review:** Ask for review before main commit (especially render/audio changes)
- **Questions:** Check [CLAUDE.md](../CLAUDE.md) first, then email pndmmo@gmail.com
- **Bug reports:** Create GitHub issue with: job.yaml (redacted), error output, hardware
- **Feature requests:** Propose in PDR format (see [project-overview-pdr.md](./project-overview-pdr.md))
