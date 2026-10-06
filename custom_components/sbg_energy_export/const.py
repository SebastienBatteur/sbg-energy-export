# SPDX-License-Identifier: Apache-2.0
"""Constantes de SBG Energy Export."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "sbg_energy_export"
VERSION: Final = "0.4.0"

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

# Envoi direct vers analyse.sbg-energy.com (version 0.3.0, ADR-038). DÉSACTIVÉ par
# défaut : seul appel réseau sortant de l'intégration, et seulement si le client
# l'active ET connecte son compte SBG Energy (flux « Device Authorization Grant »
# de Keycloak, client PUBLIC : aucun mot de passe ni secret dans Home Assistant).
OPT_ENVOI: Final = "envoi_actif"
OPT_PAS_ENVOI: Final = "pas_envoi"
OPT_DECONNECTER: Final = "deconnecter"
# Version 0.4.0 (décisions du 06/10/2026) : code postal OBLIGATOIRE pour envoyer (Home
# Assistant ne le connaît pas ; tarifs du réseau, région, météo de la zone, jamais
# d'adresse) et case FACULTATIVE « Améliorer les outils SBG », décochée par défaut.
OPT_CODE_POSTAL: Final = "code_postal"
OPT_AMELIORER: Final = "ameliorer_outils"
PAS_ENVOI_DEFAUT: Final = 15
DATA_JETON: Final = "jeton_rafraichissement"   # jeton de rafraîchissement (jamais journalisé)
DATA_SOURCE: Final = "source"                   # identifiant ALÉATOIRE de cette installation
AUTH_URL: Final = "https://auth.sbg-energy.com/realms/sbg"
API_URL: Final = "https://analyse.sbg-energy.com/api/v1/ha"
CLIENT_ID: Final = "sbg-ha-export"
PORTEES: Final = "offline_access ha-export"
SERVICE_ENVOYER: Final = "envoyer"
SERVICE_REIMPORTER: Final = "reimporter"
# Jours par morceau envoyé (le service en accepte 92 au plus, 1 Mo au plus).
JOURS_PAR_MORCEAU: Final = {5: 10, 15: 31, 60: 92}
OCTETS_MAX: Final = 900_000
# Le jeton de rafraîchissement hors ligne expire s'il n'est pas utilisé pendant 30 jours
# (réglage du royaume) : il est renouvelé chaque semaine (appel à auth.sbg-energy.com seul).
RENOUVELER_JETON_J: Final = 7
