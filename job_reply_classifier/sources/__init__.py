"""Sources: where mail comes from."""
from .base import Source
from .fixtures import FixtureSource
from .gmail import GmailError, GmailSource

__all__ = ["FixtureSource", "GmailError", "GmailSource", "Source"]
