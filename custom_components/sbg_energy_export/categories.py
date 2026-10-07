# SPDX-License-Identifier: Apache-2.0
"""Catégorie proposée pour chaque appareil, et appareils recommandés pour l'analyse.

Règles déterministes (aucune IA), dans cet ordre :

1. mots du **nom** de l'appareil dans le tableau Énergie (ou du capteur), puis du
   nom, du modèle et du fabricant de l'**appareil Home Assistant** qui porte le
   capteur (français, néerlandais, anglais, allemand ; début de mot, accents et
   tirets bas ignorés : ``pac_appoint_ecs`` se lit « pac appoint ecs ») ;
2. **puissance typique** : une heure à 5,5 kWh ou plus (5,5 kW de moyenne pendant
   une heure entière) n'arrive dans un logement qu'avec la recharge d'une voiture ;
3. sinon ``autre``.

Ordre des règles de mots (0.5.0, retour d'une vraie installation le 07/10/2026) : la
PREMIÈRE règle qui reconnaît un mot gagne, et les plus spécifiques passent avant :

* un **port PoE** de switch alimente un petit appareil réseau : toujours
  « informatique », quel que soit le mot qui suit (« port PAC PoE » n'est pas une PAC) ;
* l'**eau chaude sanitaire** (ECS, ballon, boiler…) passe avant la PAC : « appoint ECS
  de la PAC » chauffe de l'eau, pas la maison ;
* « UV » avec « eau » est un traitement de l'eau (catégorie « pompe »), pas un éclairage ;
* les mots qui désignent un simple **support d'alimentation** (prise, multiprise,
  plug, stopcontact, Steckdose) ne sont pas des indices : on lit le reste du nom.

L'utilisateur corrige toujours la proposition.
"""
from __future__ import annotations

import re
import unicodedata

# Un indice est un mot ou une suite de mots, reconnu au DÉBUT d'un mot (« lave linge »
# reconnaît « lave-linge ») ; « = » à la fin : le mot entier seulement (« ecs= » ne
# reconnaît pas « ecstasy ») ; « a+b » : les deux indices dans le même nom ; « re: » :
# une expression régulière sur le texte normalisé (mots séparés par une espace,
# entourés d'espaces).
INDICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 1. Port PoE d'un switch : un petit appareil réseau, jamais la catégorie du mot qui suit.
    ("informatique", ("poe=",)),
    # 2. Eau chaude sanitaire, avant la PAC (« appoint ECS » de la PAC = eau chaude).
    ("ballon", ("ecs=", "ballon", "boiler", "chauffe eau", "water heater", "warmwater", "warm water",
                "warmwasser", "sanitaire", "thermodynamique", "cumulus", "eau chaude")),
    # 3. Traitement de l'eau par UV, avant l'éclairage (« lampe UV eau »).
    ("pompe", ("uv=+eau=", "uv=+water", "uv=+wasser", "adoucisseur", "waterontharder", "water softener",
               "enthartung")),
    ("voiture", ("voiture", "borne", "wallbox", "charger", "chargeur", "laadpaal", "laadpunt", "ladestation",
                 "ev", "car", "tesla", "zoe", "recharge", "easee", "zaptec", "zappi", "alfen", "peblar")),
    ("lavage", ("lave linge", "lave vaisselle", "seche linge", "machine a laver",
                "washing", "washer", "dryer", "dishwasher", "wasmachine", "droogkast", "droger", "vaatwas",
                "waschmaschine", "trockner", "geschirrsp", "lessive")),
    ("froid", ("frigo", "refrigerateur", "congelateur", "fridge", "freezer",
               "koelkast", "diepvries", "vriezer", "kuhlschrank", "gefrier", "cave a vin")),
    ("pac", ("pac", "pompe a chaleur", "heat pump", "heatpump", "warmtepomp", "warmepumpe",
             "airco", "clim", "chauffage", "heating", "verwarming", "heizung", "radiateur", "convecteur",
             "degivrage")),
    # Après la PAC : « pompe à chaleur » est une PAC, « pompe de citerne » une pompe.
    ("ventilation", ("ventil", "vmc=", "comfoair", "comfo", "wtw=", "mvhr=", "luftung", "air extract",
                     "extracteur")),
    ("pompe", ("pompe", "pump", "pomp", "pumpe", "citerne", "regenwater", "rainwater", "reservoir", "piscine",
               "pool", "zwembad", "forage", "puits", "osmose")),
    ("cuisson", ("four", "oven", "cuisson", "cuisini", "induction", "kookplaat", "plaque", "taque", "cooking", "hob",
                 "micro", "fornuis", "herd", "backofen", "kochfeld", "airfryer", "bouilloire", "kettle", "waterkoker")),
    ("informatique", ("ordinateur", "informatique", "pc", "computer", "serveur", "server", "nas", "box", "routeur",
                      "router", "modem", "switch", "reseau", "network", "netwerk", "imprimante", "printer",
                      "tv", "tele", "television", "console", "multimedia", "rack", "starlink",
                      r"re: ap\d*(?= )", "access point", "point d acces", "wifi", "home assistant",
                      "homeassistant", "raspberry", "unifi")),
    ("eclairage", ("eclairage", "lumiere", "lampe", "light", "lighting", "verlichting",
                   "licht", "led", "spots")),
)

SEUIL_VOITURE_KWH_H = 5.5

# Intérêt pour l'analyse : 1 = gros consommateurs et pilotables, 2 = utiles,
# 3 = fond (tourne en continu), 4 = sans catégorie.
PRIORITE: dict[str, int] = {
    "voiture": 1, "pac": 1, "ballon": 1, "cuisson": 2, "lavage": 2,
    "froid": 3, "informatique": 3, "eclairage": 3, "ventilation": 3, "pompe": 3, "autre": 4,
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
        "ventilation": "facultatif : tourne en continu (consommation de fond)",
        "pompe": "facultatif : pompes et traitement de l'eau, souvent en continu",
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
        "ventilation": "optional: runs all the time (base load)",
        "pompe": "optional: pumps and water treatment, often running all the time",
        "autre": "optional",
    },
    "nl": {
        "voiture": "aanbevolen: scheidt het laden van de auto van de rest van de woning",
        "pac": "aanbevolen: scheidt de verwarming, een grote en stuurbare verbruiker",
        "ballon": "aanbevolen: warm water kan de zon of de daluren volgen",
        "cuisson": "nuttig: maaltijden en vermogenspieken",
        "lavage": "nuttig: toestellen die men kan verschuiven",
        "froid": "optioneel: draait voortdurend (basisverbruik)",
        "informatique": "optioneel: netwerk en stand-by (basisverbruik)",
        "eclairage": "optioneel: klein deel van het verbruik",
        "ventilation": "optioneel: draait voortdurend (basisverbruik)",
        "pompe": "optioneel: pompen en waterbehandeling, vaak voortdurend",
        "autre": "optioneel",
    },
    "de": {
        "voiture": "empfohlen: trennt das Laden des Autos vom Rest des Hauses",
        "pac": "empfohlen: trennt die Heizung, ein großer und steuerbarer Verbraucher",
        "ballon": "empfohlen: Warmwasser kann der Sonne oder dem Niedertarif folgen",
        "cuisson": "nützlich: Mahlzeiten und Leistungsspitzen",
        "lavage": "nützlich: Geräte, die sich verschieben lassen",
        "froid": "optional: läuft ständig (Grundlast)",
        "informatique": "optional: Netzwerk und Standby (Grundlast)",
        "eclairage": "optional: kleiner Teil des Verbrauchs",
        "ventilation": "optional: läuft ständig (Grundlast)",
        "pompe": "optional: Pumpen und Wasseraufbereitung, oft im Dauerbetrieb",
        "autre": "optional",
    },
}
LIBELLES: dict[str, dict[str, str]] = {
    "fr": {"voiture": "Voiture / borne", "pac": "PAC / chauffage", "ballon": "Eau chaude", "cuisson": "Cuisson",
           "lavage": "Lavage", "froid": "Froid", "informatique": "Informatique et réseau",
           "eclairage": "Éclairage", "ventilation": "Ventilation", "pompe": "Pompes et eau", "autre": "Autre"},
    "en": {"voiture": "Car / charger", "pac": "Heat pump / heating", "ballon": "Hot water", "cuisson": "Cooking",
           "lavage": "Washing", "froid": "Cold", "informatique": "IT and network", "eclairage": "Lighting",
           "ventilation": "Ventilation", "pompe": "Pumps and water", "autre": "Other"},
    "nl": {"voiture": "Auto / laadpaal", "pac": "Warmtepomp / verwarming", "ballon": "Warm water", "cuisson": "Koken",
           "lavage": "Wassen", "froid": "Koeling", "informatique": "IT en netwerk", "eclairage": "Verlichting",
           "ventilation": "Ventilatie", "pompe": "Pompen en water", "autre": "Overige"},
    "de": {"voiture": "Auto / Ladestation", "pac": "Wärmepumpe / Heizung", "ballon": "Warmwasser", "cuisson": "Kochen",
           "lavage": "Waschen", "froid": "Kühlung", "informatique": "IT und Netzwerk", "eclairage": "Beleuchtung",
           "ventilation": "Lüftung", "pompe": "Pumpen und Wasser", "autre": "Sonstiges"},
}


def _mots(texte: str) -> str:
    """« Pac_Appoint-ÉCS » → `` pac appoint ecs `` (minuscules, sans accents, mots séparés)."""
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte.casefold())
                           if not unicodedata.combining(c))
    return " " + " ".join(re.findall(r"[^\W_]+", sans_accents)) + " "


def _indice(n: str, indice: str) -> bool:
    """L'indice est-il dans le texte normalisé ``n`` ?"""
    if indice.startswith("re:"):
        return re.search(" " + indice[3:].strip(), n) is not None
    if "+" in indice:
        return all(_indice(n, partie) for partie in indice.split("+"))
    entier = indice.endswith("=")
    mot = _mots(indice.rstrip("=")).strip()
    return f" {mot}{' ' if entier else ''}" in n


def par_le_nom(*textes: str | None) -> str | None:
    """Catégorie trouvée dans le premier texte qui en donne une, sinon ``None``."""
    for texte in textes:
        if not texte:
            continue
        n = _mots(texte)
        for categorie, indices in INDICES:
            if any(_indice(n, i) for i in indices):
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
    """``fr``, ``nl``, ``de`` ou ``en`` (les autres langues reçoivent l'anglais)."""
    prefixe = (code or "").lower()[:2]
    return prefixe if prefixe in RAISONS else "en"


def libelle(nom: str, categorie: str, code_langue: str | None) -> str:
    """« Borne garage — Voiture / borne · recommandé : … »."""
    lg = langue(code_langue)
    return f"{nom} — {LIBELLES[lg].get(categorie, categorie)} · {RAISONS[lg].get(categorie, '')}"


def recommande(categorie: str) -> bool:
    """Coché par défaut dans une sélection."""
    return PRIORITE.get(categorie, 4) <= RECOMMANDE_JUSQUA
