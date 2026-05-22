class VideoToolError(Exception):
    """Base error for user-facing failures."""


class ConfigError(VideoToolError):
    pass


class DependencyError(VideoToolError):
    pass


class LicensePolicyError(VideoToolError):
    pass


class RenderError(VideoToolError):
    pass


class ValidationError(VideoToolError):
    pass
