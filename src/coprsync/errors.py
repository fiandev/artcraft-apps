class CoprSyncError(Exception):
    """Base class for every failure coprsync reports to the CLI."""


class ConfigError(CoprSyncError):
    """config/apps.yaml is missing or invalid."""


class GitHubError(CoprSyncError):
    """A GitHub API call failed."""


class RpmError(CoprSyncError):
    """Inspecting or rebuilding an upstream RPM failed."""


class CoprError(CoprSyncError):
    """Creating a project or submitting a build failed."""
