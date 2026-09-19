"""Shared pytest configuration. Track A owns this file (plan §17)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers import Stack, build_stack  # noqa: E402


@pytest.fixture
async def stack_factory():
    """Factory for wired provider+store stacks; closes every client at test end."""
    created: list[Stack] = []

    async def factory(*, namespace: str) -> Stack:
        stack = await build_stack(namespace=namespace)
        created.append(stack)
        return stack

    yield factory

    for stack in created:
        await stack.aclose()
