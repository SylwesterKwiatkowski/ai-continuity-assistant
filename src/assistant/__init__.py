"""AI Business Continuity Assistant.

A governed work-context assistant. See docs/ for architecture and security model.

The one rule that governs everything:
    Read with delegated, scoped permission.
    Write only as the active user.
    Never impersonate the target user.
"""

__version__ = "0.0.1"
