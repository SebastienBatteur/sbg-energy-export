"""Constantes de SBG Energy Export."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "sbg_energy_export"
VERSION: Final = "0.2.0"

# Dossier de travail, dans le dossier de configuration de Home Assistant.
DOSSIER: Final = "sbg_energy_export"
SOUS_DOSSIER_MESURES: Final = "mesures"
ANCIEN_SOUS_DOSSIER_QUARTS: Final = "quarts"  # version 0.1.0, migré au démarrage
SOUS_DOSSIER_EXPORTS: Final = "exports"

# Options de l'entrée de configuration.
OPT_CHOIX: Final = "choix"            # tous, aucun, selection
OPT_APPAREILS: Final = "appareils"    # statistiques choisies (selection)
OPT_CATEGORIES: Final = "categories"  # statistique -> catégorie
OPT_CONSERVATION: Final = "conservation_ans"  # durée de conservation locale
OPT_CINQ_MINUTES: Final = "pas_5min"          # garder le pas de 5 min
CONSERVATION_DEFAUT: Final = 3
CONSERVATION_MAX: Final = 30
CHOIX_TOUS: Final = "tous"
CHOIX_AUCUN: Final = "aucun"
CHOIX_SELECTION: Final = "selection"

SERVICE_EXPORTER: Final = "exporter"
ATTR_PAS: Final = "pas"
ATTR_DEBUT: Final = "debut"
ATTR_FIN: Final = "fin"

# Quarts d'heure : traités 2 min après leur fin (les statistiques de 5 min sont
# compilées quelques secondes après chaque période de 5 min).
DELAI_QUART_S: Final = 120
VALIDITE_LIEN_H: Final = 1
