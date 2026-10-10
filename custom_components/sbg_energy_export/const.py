# SPDX-License-Identifier: Apache-2.0
"""Constantes de SBG Energy Export."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "sbg_energy_export"
VERSION: Final = "0.6.2"

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

# Envoi direct vers analyse.sbg-energy.com (version 0.3.0). DÉSACTIVÉ par
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
# Version 0.6.0 (ADR-040, étape 7) : gestionnaire du réseau de distribution, FACULTATIF, et
# logement du compte où l'installation envoie (choisi seulement si le service en donne la liste).
# « inconnu » (« je ne sais pas ») n'est jamais envoyé : le service garde la valeur qu'il a, ou
# déduit le gestionnaire du code postal quand il est certain.
OPT_GRD: Final = "grd"
OPT_LOGEMENT: Final = "logement"
GRD_INCONNU: Final = "inconnu"
# Version 0.6.1 : cases de l'étape « confirmer » (décochées par défaut), montrées quand l'étape
# Envoi reçoit décoché un interrupteur qu'elle montrait coché. Jamais gardées dans les options.
CONF_ARRET: Final = "confirmer_arret"        # désactiver l'envoi
CONF_RETRAIT: Final = "confirmer_retrait"    # retirer l'accord (le service efface les copies)
GRDS: Final = ("ores", "resa", "aieg", "aiesh", "rew", "sibelga", "fluvius")
# Texte de l'étape Envoi accepté par l'utilisateur, nommé dans chaque requête de réglages (champ
# ``texte_consentement``) pour que le service garde comme preuve le texte réellement affiché
# (décision du 09/10/2026 : un champ explicite, pas la version lue dans le User-Agent).
# Ce n'est NI ``ENVOI_HA`` (0.5 : « le rapport de votre compte », 3 installations) NI
# ``ENVOI_HA_LOGEMENT`` (qui contient CONSERVATION_LOGEMENT, pas encore publiée) : c'est le texte
# « votre logement » avec la phrase de conservation de 0.5.1 (« tout supprimé après 3 ans
# glissants »). Quand l'étape 5 du service publiera CONSERVATION_LOGEMENT, l'intégration
# l'affichera et enverra ``ENVOI_HA_LOGEMENT``. Changer cette valeur avec le texte affiché.
TEXTE_CONSENTEMENT: Final = "ENVOI_HA_LOGEMENT_AVANT_ETAPE_5"
PAS_ENVOI_DEFAUT: Final = 15
DATA_JETON: Final = "jeton_rafraichissement"   # jeton de rafraîchissement (jamais journalisé)
DATA_SOURCE: Final = "source"                   # identifiant ALÉATOIRE de cette installation
AUTH_URL: Final = "https://auth.sbg-energy.com/realms/sbg"
API_URL: Final = "https://analyse.sbg-energy.com/api/v1/ha"
# Conditions du service, données à l'écran « Envoi » par un paramètre (hassfest refuse les URL
# dans les traductions).
URL_CONDITIONS: Final = "https://analyse.sbg-energy.com/conditions/#home-assistant"
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
