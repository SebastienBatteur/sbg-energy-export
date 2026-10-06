# SPDX-License-Identifier: Apache-2.0
"""Assemble ``outils/sbg_ha_export.py`` : un seul fichier à donner à l'utilisateur.

    python outils/assembler_script.py

Le fichier produit = en-tête + bloc partagé de ``sbg_format.py`` (copie
identique, vérifiée par ``tests/test_script.py``) + ``script_principal.py``.
"""
from pathlib import Path

ICI = Path(__file__).resolve().parent
MODULE = ICI.parent / "custom_components" / "sbg_energy_export" / "sbg_format.py"
DEBUT = "# === CODE PARTAGE : debut"
FIN = "# === CODE PARTAGE : fin ==="

ENTETE = '''#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sbg_ha_export.py : exporte les données du tableau Énergie de Home Assistant
au format ouvert « SBG HA export » (CSV), pour le déposer soi-même sur
analyse.sbg-energy.com.

Python 3.9 ou plus récent, bibliothèque standard seulement : rien à installer.
Le script ne parle qu'à VOTRE Home Assistant (adresse donnée avec --url). Le
jeton d'accès est demandé au clavier (ou lu dans la variable SBG_HA_JETON),
n'est jamais écrit sur disque, et ne doit être transmis à personne.

Exemples :
    python sbg_ha_export.py --url http://homeassistant.local:8123
    python sbg_ha_export.py --url http://homeassistant.local:8123 --pas 15
    python sbg_ha_export.py --depuis-csv energy*.csv --appareil sensor.borne=voiture

Fichier généré par outils/assembler_script.py : ne pas modifier à la main.
Licence : Apache-2.0 (voir LICENSE et NOTICE du dépôt sbg-energy-export).
"""
from __future__ import annotations
'''


def bloc_partage(texte: str) -> str:
    """Le code entre les deux marqueurs, marqueurs compris."""
    i = texte.index(DEBUT)
    j = texte.index(FIN) + len(FIN)
    return texte[i:j] + "\n"


def assembler() -> str:
    partage = bloc_partage(MODULE.read_text(encoding="utf-8"))
    principal = (ICI / "script_principal.py").read_text(encoding="utf-8")
    return ENTETE + "\n" + partage + principal


if __name__ == "__main__":
    (ICI / "sbg_ha_export.py").write_text(assembler(), encoding="utf-8", newline="\n")
    print("outils/sbg_ha_export.py assemblé")
