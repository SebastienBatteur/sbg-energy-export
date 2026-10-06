# SPDX-License-Identifier: Apache-2.0
"""Tests de SBG Energy Export."""

from pathlib import Path
import zipfile


def lire_zip(chemin: Path) -> str:
    """Texte du CSV unique d'un export (ZIP depuis 0.5.0), dont le nom suit celui de l'archive."""
    with zipfile.ZipFile(chemin) as z:
        assert z.namelist() == [chemin.name[:-4] + ".csv"]
        return z.read(z.namelist()[0]).decode("utf-8")
