"""The two failure types the watcher treats differently."""


class ClassificationError(Exception):
    """No valid answer this time. The mail stays unseen and is retried next cycle."""


class ConfigError(Exception):
    """A setup problem (bad key, revoked token, missing CLI). Retrying will not help, so the cycle stops."""
