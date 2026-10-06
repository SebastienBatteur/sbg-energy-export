# SPDX-License-Identifier: Apache-2.0
"""Fixtures communes.

Le tableau Énergie dépend du recorder : le recorder (SQLite en mémoire) doit être
préparé AVANT ``hass``, d'où l'ordre des fixtures ci-dessous."""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Recorder de test, puis intégrations de custom_components, dans chaque test."""
    yield
