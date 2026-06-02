from __future__ import annotations

from pathlib import Path

from videotool.core.job_spec import JobSpec


def validate_job_paths(job: JobSpec, job_path: Path, require_existing: bool = True) -> list[str]:
    root = job_path.parent.resolve()
    errors: list[str] = []
    candidates = [root / job.inputs.voice, root / job.inputs.media_dir]
    if job.inputs.music:
        candidates.append(root / job.inputs.music)
    if job.inputs.script:
        candidates.append(root / job.inputs.script)
    if job.inputs.intro_image:
        candidates.append(root / job.inputs.intro_image)
    if job.inputs.ending_image:
        candidates.append(root / job.inputs.ending_image)
    if job.inputs.particle_overlay:
        candidates.append(root / job.inputs.particle_overlay)
    if job.inputs.description_template:
        candidates.append(root / job.inputs.description_template)
    for cta_path in (job.inputs.intro_cta, job.inputs.outro_cta, job.inputs.intro_cta_image, job.inputs.outro_cta_image):
        if cta_path:
            candidates.append(root / cta_path)
    candidates.extend(root / scene.image for scene in job.storyboard)
    candidates.append(root / job.render.temp_dir)
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"Path escapes job folder: {candidate}")
        elif require_existing and candidate != root / job.render.temp_dir and not resolved.exists():
            errors.append(f"Path does not exist: {candidate}")
    return errors
