"""Creative layer shared by the local and cloud render paths.

Job preparation, the Claude/agent-authored `creative.yaml` merge, the SFX/music rules the render
box enforces, and the lint + sfx-pin tools that replay those rules before anything is staged.
One copy of every rule, so local, cloud and lint cannot drift apart again.
"""

from videotool.creative.rules import CreativeError

__all__ = ["CreativeError"]
