"""Shared test setup."""

from __future__ import annotations

import pytest

from agent_ab import workspace


@pytest.fixture(autouse=True, scope="session")
def _workspaces_under_tmp(tmp_path_factory):
    # The default workspace root can be outside the system temp directory (on Windows it is at
    # the root of the home drive); keep test workspaces under pytest's temp directory. Session
    # scope, so module-scoped fixtures that run experiments see it too.
    root = tmp_path_factory.getbasetemp() / "workspaces"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(workspace, "default_workspace_root", lambda: root)
        yield
