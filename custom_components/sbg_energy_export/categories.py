# SPDX-License-Identifier: Apache-2.0
"""Catégorie proposée pour chaque appareil, et appareils recommandés pour l'analyse.

Règles déterministes (aucune IA), dans cet ordre :

1. mots du **nom** de l'appareil dans le tableau Énergie (ou du capteur), puis du
   nom, du modèle et du fabricant de l'**appareil Home Assistant** qui porte le
   capteur (français, néerlandais, anglais, allemand ; début de mot) ;
2. **puissance typique** : une heure à 5,5 kWh ou plus (5,5 kW de moyenne pendant
   une heure entière) n'arrive dans un logement qu'avec la recharge d'une voiture ;
3. sinon ``autre``.

L'utilisateur corrige toujours la proposition.
"""
from __future__ import annotations

import re

# Ordre d'essai : du plus spécifique au plus général (« lave-vaisselle » avant
# « vaisselle », « frigo » avant « cuisine »...).
INDICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("voiture", ("voiture", "borne", "wallbox", "charger", "chargeur", "laadpaal", "laadpunt", "ladestation",
                 "ev", "car", "tesla", "zoe", "recharge", "easee", "zaptec", "zappi", "alfen", "peblar")),
    ("lavage", ("lave linge", "lave vaisselle", "seche linge", "sèche linge", "machine a laver", "machine à laver",
                "washing", "washer", "dryer", "dishwasher", "wasmachine", "droogkast", "droger", "vaatwas",
                "waschmaschine", "trockner", "geschirrsp", "lessive")),
    ("froid", ("frigo", "refrigerateur", "réfrigérateur", "congelateur", "congélateur", "fridge", "freezer",
               "koelkast", "diepvries", "vriezer", "kühlschrank", "kuhlschrank", "gefrier", "cave a vin", "cave à vin")),
    ("pac", ("pac", "pompe a chaleur", "pompe à chaleur", "heat pump", "heatpump", "warmtepomp", "wärmepumpe",
             "airco", "clim", "chauffage", "heating", "verwarming", "heizung", "radiateur", "convecteur")),
    ("ballon", ("ballon", "boiler", "chauffe eau", "water heater", "ecs", "warmwater", "sanitaire", "thermodynamique")),
    ("cuisson", ("four", "oven", "cuisson", "cuisini", "induction", "kookplaat", "plaque", "taque", "cooking", "hob",
                 "micro", "fornuis", "herd", "backofen", "kochfeld", "airfryer", "bouilloire", "kettle", "waterkoker")),
    ("informatique", ("ordinateur", "informatique", "pc", "computer", "serveur", "server", "nas", "box", "routeur",
                      "router", "modem", "switch", "reseau", "réseau", "network", "netwerk", "imprimante", "printer",
                      "tv", "tele", "télé", "television", "télévision", "console", "multimedia", "multimédia", "rack")),
    ("eclairage", ("eclairage", "éclairage", "lumiere", "lumière", "lampe", "light", "lighting", "verlichting",
                   "licht", "led", "spots")),
)

SEUIL_VOITURE_KWH_H = 5.5

# Intérêt pour l'analyse : 1 = gros consommateurs et pilotables, 2 = utiles,
# 3 = fond (tourne en continu), 4 = sans catégorie.
PRIORITE: dict[str, int] = {
    "voiture": 1, "pac": 1, "ballon": 1, "cuisson": 2, "lavage": 2,
    "froid": 3, "informatique": 3, "eclairage": 3, "autre": 4,
}
RECOMMANDE_JUSQUA = 2  # cochés par défaut dans une sélection

RAISONS: dict[str, dict[str, str]] = {
    "fr": {
        "voiture": "recommandé : sépare la recharge de la voiture du reste de la maison",
        "pac": "recommandé : sépare le chauffage, gros poste et pilotable",
        "ballon": "recommandé : l'eau chaude peut suivre le soleil ou les heures creuses",
        "cuisson": "utile : repas et pics de puissance",
        "lavage": "utile : appareils que l'on peut décaler",
        "froid": "facultatif : tourne en continu (consommation de fond)",
        "informatique": "facultatif : réseau et veille (consommation de fond)",
        "eclairage": "facultatif : petite part de la consommation",
        "autre": "facultatif",
    },
    "en": {
        "voiture": "recommended: separates car charging from the rest of the home",
        "pac": "recommended: separates heating, a large and controllable load",
        "ballon": "recommended: hot water can follow the sun or off-peak hours",
        "cuisson": "useful: meals and power peaks",
        "lavage": "useful: appliances that can be shifted",
        "froid": "optional: runs all the time (base load)",
        "informatique": "optional: network and standby (base load)",
        "eclairage": "optional: small share of consumption",
        "autre": "optional",
    },
}
LIBELLES: dict[str, dict[str, str]] = {
    "fr": {"voiture": "Voiture / borne", "pac": "PAC / chauffage", "ballon": "Eau chaude", "cuisson": "Cuisson",
           "lavage": "Lavage", "froid": "Froid", "informatique": "Informatique et réseau",
           "eclairage": "Éclairage", "autre": "Autre"},
    "en": {"voiture": "Car / charger", "pac": "Heat pump / heating", "ballon": "Hot water", "cuisson": "Cooking",
           "lavage": "Washing", "froid": "Cold", "informatique": "IT and network", "eclairage": "Lighting",
           "autre": "Other"},
}


def _mots(texte: str) -> str:
    return " " + " ".join(re.findall(r"\w+", texte.casefold())) + " "


def par_le_nom(*textes: str | None) -> str | None:
    """Catégorie trouvée dans le premier texte qui en donne une, sinon ``None``."""
    for texte in textes:
        if not texte:
            continue
        n = _mots(texte)
        for categorie, mots in INDICES:
            if any(f" {_mots(m).strip()}" in n for m in mots):  # début de mot
                return categorie
    return None


def deviner_categorie(nom: str, *autres: str | None, kwh_h_max: float | None = None) -> str:
    """Catégorie proposée : nom, puis appareil Home Assistant, puis puissance typique."""
    trouvee = par_le_nom(nom, *autres)
    if trouvee:
        return trouvee
    if kwh_h_max is not None and kwh_h_max >= SEUIL_VOITURE_KWH_H:
        return "voiture"
    return "autre"


def langue(code: str | None) -> str:
    """``fr`` ou ``en`` (les autres langues reçoivent l'anglais)."""
    return "fr" if (code or "").lower().startswith("fr") else "en"


def libelle(nom: str, categorie: str, code_langue: str | None) -> str:
    """« Borne garage — Voiture / borne · recommandé : … »."""
    lg = langue(code_langue)
    return f"{nom} — {LIBELLES[lg].get(categorie, categorie)} · {RAISONS[lg].get(categorie, '')}"


def recommande(categorie: str) -> bool:
    """Coché par défaut dans une sélection."""
    return PRIORITE.get(categorie, 4) <= RECOMMANDE_JUSQUA
