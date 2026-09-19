"""Trusted mock payment provider (plan §5.3, §9.3). Track A-owned."""

from apps.trusted_provider.app import create_app

__all__ = ["create_app"]
