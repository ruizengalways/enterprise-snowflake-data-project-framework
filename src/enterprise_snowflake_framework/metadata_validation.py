"""Backward-compatible import surface for validation utilities.

New code should import :mod:`enterprise_snowflake_framework.validation`.
"""

from .validation import *  # noqa: F401,F403
