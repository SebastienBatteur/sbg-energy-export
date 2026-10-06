# SPDX-License-Identifier: Apache-2.0
"""Format « SBG HA export », versions 1 et 2 : construction et écriture du fichier.

Ce module est en Python pur (bibliothèque standard seulement) : il ne dépend pas
de Home Assistant. Il sert à l'intégration ET au script manuel
``outils/sbg_ha_export.py``, qui en embarque une copie identique (un test le
vérifie). Spécification : ``FORMAT_SBG_HA_EXPORT.md``.

Principes :
  * version 1 : une ligne par pas de temps (5, 15 ou 60 min), horodatée au
    DÉBUT de l'intervalle, en UTC ; le passé connu seulement à l'heure est
    réparti en parts égales au pas du fichier ;
  * version 2 (« compacte », 0.5.0) : le passé connu seulement à l'heure reste
    en lignes HORAIRES, seules les heures vraiment mesurées au pas fin sont au
    pas fin. La durée d'une ligne se lit sur sa provenance. Douze fois moins de
    lignes pour trois ans au pas de 5 min ; l'export manuel l'utilise, l'envoi
    direct garde la version 1 (le service range les envois par jours complets
    au pas de la session) ;
  * énergies en kWh sur l'intervalle ; cellule vide = inconnu (jamais un zéro
    déguisé) ;
  * chaque ligne dit d'où elle vient (provenance) ;
  * rien de plus que nécessaire : ni identifiant d'entité, ni nom d'appareil,
    ni pièce, ni position. Les appareils deviennent « voiture_1 », « pac_1 »...
"""
from __future__ import annotations

# === CODE PARTAGE : debut (copie identique dans outils/sbg_ha_export.py) ===
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

FORMAT = "SBG HA export"
VERSION = 1
VERSION_COMPACTE = 2

# Colonnes d'énergie fixes, dans l'ordre du fichier.
PRELEVEMENT = "prelevement_reseau"
INJECTION = "injection_reseau"
SOLAIRE = "production_solaire"
CHARGE = "charge_batterie"
DECHARGE = "decharge_batterie"
CONSO = "consommation_maison"
ROLES: tuple[str, ...] = (PRELEVEMENT, INJECTION, SOLAIRE, CHARGE, DECHARGE)
COLONNES_FIXES: tuple[str, ...] = (*ROLES, CONSO)

# Liste fermée. Les 5 premières existent depuis le début ; lavage, froid,
# informatique et eclairage ajoutées le 06/10/2026, ventilation et pompe (pompes
# et traitement de l'eau : citerne, piscine, UV, adoucisseur) le 07/10/2026
# (extensions compatibles : un fichier qui ne les utilise pas ne change pas).
CATEGORIES: tuple[str, ...] = ("voiture", "pac", "ballon", "cuisson", "lavage", "froid", "informatique",
                               "eclairage", "ventilation", "pompe", "autre")

MESURE_5 = "mesure_5min"
MESURE_15 = "mesure_15min"
MESURE_60 = "mesure_60min"
HEURE_REPARTIE = "heure_repartie"
TROU = "trou"
TROU_60 = "trou_60min"  # version 2 : heure entière inconnue, en UNE ligne
PROVENANCES: tuple[str, ...] = (MESURE_5, MESURE_15, MESURE_60, HEURE_REPARTIE, TROU, TROU_60)
# Version 2 : ces provenances durent une heure, les autres le pas du fichier.
PROVENANCES_HORAIRES: tuple[str, ...] = (MESURE_60, TROU_60)

# Pas permis (minutes) et provenance d'une mesure à ce pas. Le pas de 5 min est
# celui des statistiques à court terme de Home Assistant, sans regroupement.
PAS_MINUTES: tuple[int, ...] = (5, 15, 60)
MESURE_AU_PAS: dict[int, str] = {5: MESURE_5, 15: MESURE_15, 60: MESURE_60}

# Au-delà de 60 kW de moyenne, ce n'est pas un logement : c'est un compteur qui
# rattrape d'un coup l'énergie d'une coupure. La période est laissée inconnue.
PUISSANCE_MAX_KW = 60.0

# Un bilan négatif de moins de 10 Wh est un arrondi des compteurs : ramené à 0.
TOLERANCE_BILAN_KWH = 0.01

UTC = timezone.utc


@dataclass(frozen=True)
class Appareil:
    """Un appareil du tableau Énergie retenu par l'utilisateur."""

    statistique: str  # identifiant local (jamais écrit dans le fichier)
    categorie: str
    parent: str | None = None  # statistique de l'appareil qui le contient


@dataclass(frozen=True)
class Colonne:
    """Colonne d'appareil telle qu'elle apparaît dans le fichier."""

    nom: str
    categorie: str
    statistique: str
    inclus_dans: str | None = None


@dataclass
class Configuration:
    """Quelles statistiques alimentent quelles colonnes."""

    roles: dict[str, list[str]] = field(default_factory=dict)
    appareils: list[Appareil] = field(default_factory=list)

    def statistiques(self) -> set[str]:
        """Toutes les statistiques à lire."""
        ids = {s for liste in self.roles.values() for s in liste}
        ids.update(a.statistique for a in self.appareils)
        return ids

    def non_configures(self) -> list[str]:
        """Rôles absents du tableau Énergie (pas de panneaux, pas de batterie...)."""
        return [r for r in ROLES if not self.roles.get(r)]

    def colonnes(self) -> list[Colonne]:
        """Noms neutres : catégorie + rang dans la catégorie."""
        rangs: dict[str, int] = {}
        noms: dict[str, str] = {}
        sortie: list[Colonne] = []
        for app in self.appareils:
            if app.categorie not in CATEGORIES:
                raise ValueError(f"catégorie inconnue : {app.categorie}")
            rangs[app.categorie] = rangs.get(app.categorie, 0) + 1
            noms[app.statistique] = f"{app.categorie}_{rangs[app.categorie]}"
        for app in self.appareils:
            parent = noms.get(app.parent) if app.parent else None
            sortie.append(Colonne(noms[app.statistique], app.categorie, app.statistique, parent))
        return sortie


# --------------------------------------------------------------- préférences
def appareils_du_tableau(prefs: Mapping) -> list[dict]:
    """Appareils individuels du tableau Énergie (``device_consumption``)."""
    return [d for d in prefs.get("device_consumption") or [] if d.get("stat_consumption")]


def depuis_preferences(
    prefs: Mapping,
    choisis: Iterable[str],
    categories: Mapping[str, str],
) -> Configuration:
    """Configuration à partir de ``energy/get_prefs``.

    Gère l'ancien format du réseau (``flow_from`` / ``flow_to``) et le format
    unifié (``stat_energy_from`` / ``stat_energy_to`` sur la source réseau).
    Plusieurs sources d'un même rôle (deux tarifs, deux onduleurs) sont additionnées.
    """
    roles: dict[str, list[str]] = {r: [] for r in ROLES}
    for src in prefs.get("energy_sources") or []:
        typ = src.get("type")
        if typ == "grid":
            for flux in src.get("flow_from") or []:
                if flux.get("stat_energy_from"):
                    roles[PRELEVEMENT].append(flux["stat_energy_from"])
            for flux in src.get("flow_to") or []:
                if flux.get("stat_energy_to"):
                    roles[INJECTION].append(flux["stat_energy_to"])
            if src.get("stat_energy_from"):
                roles[PRELEVEMENT].append(src["stat_energy_from"])
            if src.get("stat_energy_to"):
                roles[INJECTION].append(src["stat_energy_to"])
        elif typ == "solar" and src.get("stat_energy_from"):
            roles[SOLAIRE].append(src["stat_energy_from"])
        elif typ == "battery":
            if src.get("stat_energy_to"):
                roles[CHARGE].append(src["stat_energy_to"])
            if src.get("stat_energy_from"):
                roles[DECHARGE].append(src["stat_energy_from"])
    choisis = set(choisis)
    appareils = [
        Appareil(d["stat_consumption"], categories.get(d["stat_consumption"], "autre"),
                 d.get("included_in_stat") or None)
        for d in appareils_du_tableau(prefs)
        if d["stat_consumption"] in choisis
    ]
    # Un parent non retenu n'est pas cité.
    retenus = {a.statistique for a in appareils}
    appareils = [a if a.parent in retenus else Appareil(a.statistique, a.categorie) for a in appareils]
    return Configuration({r: l for r, l in roles.items() if l}, appareils)


# --------------------------------------------------------------- statistiques
def en_secondes(x: float | int | str | datetime) -> int:
    """Instant en secondes UTC (WebSocket : ms ; recorder : s ; ISO accepté)."""
    if isinstance(x, datetime):
        return int(x.timestamp())
    if isinstance(x, str):
        return int(datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp())
    x = float(x)
    return int(round(x / 1000.0)) if x > 1e11 else int(round(x))


def variations(lignes: Sequence[Mapping], pas_s: int) -> dict[int, float]:
    """Énergie de chaque période, par différence des ``sum`` consécutifs.

    Une période n'est connue que si la précédente existe aussi (sinon l'énergie
    d'un trou serait attribuée à la période qui le suit) et si la différence est
    positive ou nulle, sans dépasser ``PUISSANCE_MAX_KW`` (rattrapage d'un
    compteur après une coupure). Exception sûre : des lignes manquent mais le cumul n'a pas
    bougé ; toutes les périodes du trou valent alors 0. Les ``sum`` des statistiques Home Assistant tiennent
    déjà compte des remises à zéro des compteurs.
    """
    sortie: dict[int, float] = {}
    precedent: tuple[int, float] | None = None
    for ligne in sorted(lignes, key=lambda l: en_secondes(l["start"])):
        debut = en_secondes(ligne["start"])
        somme = ligne.get("sum")
        if somme is None:
            precedent = None
            continue
        somme = float(somme)
        if precedent is not None and debut > precedent[0]:
            delta = somme - precedent[1]
            if precedent[0] + pas_s == debut:
                if math.isfinite(delta) and 0 <= delta <= PUISSANCE_MAX_KW * pas_s / 3600:
                    sortie[debut] = delta
            elif delta == 0:
                # Lignes absentes mais cumul inchangé : aucune énergie pendant le trou.
                for t in range(precedent[0] + pas_s, debut + pas_s, pas_s):
                    sortie[t] = 0.0
        precedent = (debut, somme)
    return sortie


def regrouper(valeurs: Mapping[int, float], pas_source_s: int, pas_s: int) -> dict[int, float]:
    """Somme des petites périodes (5 min) en grandes (15 min), si toutes sont connues."""
    n = pas_s // pas_source_s
    paquets: dict[int, list[float]] = {}
    for debut, v in valeurs.items():
        paquets.setdefault(debut - debut % pas_s, []).append(v)
    return {d: sum(l) for d, l in paquets.items() if len(l) == n}


# ------------------------------------------------------------------- lignes
@dataclass
class Ligne:
    """Une ligne du fichier."""

    debut: int  # secondes UTC
    provenance: str
    valeurs: dict[str, float | None]


def construire_lignes(
    config: Configuration,
    energies: Mapping[str, Mapping[int, float]],
    debut: int,
    fin: int,
    pas_s: int,
    provenance: str,
) -> list[Ligne]:
    """Lignes régulières de ``debut`` (inclus) à ``fin`` (exclu).

    ``energies`` : pour chaque statistique, énergie (kWh) par début de période.
    """
    colonnes = config.colonnes()
    configures = [r for r in ROLES if config.roles.get(r)]
    lignes: list[Ligne] = []
    t = debut - debut % pas_s
    while t < fin:
        valeurs: dict[str, float | None] = {c: None for c in COLONNES_FIXES}
        for role in configures:
            parts = [energies.get(s, {}).get(t) for s in config.roles[role]]
            valeurs[role] = None if any(p is None for p in parts) else sum(parts)  # type: ignore[arg-type]
        for col in colonnes:
            valeurs[col.nom] = energies.get(col.statistique, {}).get(t)
        if all(valeurs[r] is not None for r in configures) and configures:
            v = {r: valeurs[r] or 0.0 for r in ROLES}  # non configuré = 0 dans le bilan
            bilan = v[PRELEVEMENT] + v[SOLAIRE] - v[INJECTION] - v[CHARGE] + v[DECHARGE]
            if bilan >= -TOLERANCE_BILAN_KWH:
                valeurs[CONSO] = max(0.0, bilan)
        connu = any(x is not None for x in valeurs.values())
        lignes.append(Ligne(t, provenance if connu else TROU, valeurs))
        t += pas_s
    return lignes


def assembler(heures: Sequence[Ligne], mesures: Mapping[int, Ligne], pas_s: int) -> list[Ligne]:
    """Fichier au pas fin (5 ou 15 min) : périodes mesurées, sinon heure répartie.

    Pour chaque heure : si au moins une période est mesurée, toutes les périodes
    de l'heure viennent des mesures (celles qui manquent sont des trous) ; sinon
    l'heure est répartie en parts égales (4 au pas de 15 min, 12 au pas de
    5 min ; provenance « heure_repartie ») ; une heure inconnue donne des trous.
    Les parts d'une même heure partagent le même dictionnaire de valeurs (lu
    seulement) : un an au pas de 5 min reste léger en mémoire.
    """
    n = 3600 // pas_s
    sortie: list[Ligne] = []
    for h in heures:
        ms = [mesures.get(h.debut + pas_s * k) for k in range(n)]
        if any(m is not None and m.provenance != TROU for m in ms):
            vide: dict[str, float | None] = {c: None for c in h.valeurs}
            for k, m in enumerate(ms):
                sortie.append(m if m is not None else Ligne(h.debut + pas_s * k, TROU, vide))
        elif h.provenance == TROU:
            sortie.extend(Ligne(h.debut + pas_s * k, TROU, h.valeurs) for k in range(n))
        else:
            part = {c: (None if v is None else v / n) for c, v in h.valeurs.items()}
            sortie.extend(Ligne(h.debut + pas_s * k, HEURE_REPARTIE, part) for k in range(n))
    return sortie


def assembler_compact(heures: Sequence[Ligne], mesures: Mapping[int, Ligne], pas_s: int) -> list[Ligne]:
    """Version 2 : comme ``assembler``, mais une heure sans mesure au pas fin reste en UNE
    ligne horaire (``mesure_60min``, ou ``trou_60min`` si elle est inconnue)."""
    n = 3600 // pas_s
    sortie: list[Ligne] = []
    for h in heures:
        ms = [mesures.get(h.debut + pas_s * k) for k in range(n)]
        if any(m is not None and m.provenance != TROU for m in ms):
            vide: dict[str, float | None] = {c: None for c in h.valeurs}
            for k, m in enumerate(ms):
                sortie.append(m if m is not None else Ligne(h.debut + pas_s * k, TROU, vide))
        else:
            sortie.append(Ligne(h.debut, TROU_60 if h.provenance == TROU else MESURE_60, h.valeurs))
    return sortie


def duree_s(ligne: Ligne, pas_s: int, version: int) -> int:
    """Durée couverte par une ligne : une heure pour une ligne horaire de la version 2."""
    return 3600 if version >= 2 and ligne.provenance in PROVENANCES_HORAIRES else pas_s


def assembler_quarts(heures: Sequence[Ligne], quarts: Mapping[int, Ligne]) -> list[Ligne]:
    """Fichier au quart d'heure : quarts mesurés, sinon heure répartie en 4."""
    return assembler(heures, quarts, 900)


# ------------------------------------------------------------------ écriture
def iso(secondes: int) -> str:
    """``2026-10-06T08:15:00Z``."""
    return datetime.fromtimestamp(secondes, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def nombre(x: float | None) -> str:
    """kWh à 4 décimales au plus, sans zéros inutiles ; vide si inconnu."""
    if x is None:
        return ""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def ecrire(
    config: Configuration,
    lignes: Sequence[Ligne],
    pas_minutes: int,
    fuseau: str,
    generateur: str,
    genere_le: int,
    version: int = VERSION,
) -> str:
    """Texte complet du fichier (UTF-8, fin de ligne LF, séparateur virgule)."""
    if pas_minutes not in PAS_MINUTES:
        raise ValueError("pas de 5, 15 ou 60 minutes seulement")
    if version not in (VERSION, VERSION_COMPACTE):
        raise ValueError("version 1 ou 2 seulement")
    colonnes = config.colonnes()
    pas_s = pas_minutes * 60
    # Premier instant mesuré au pas fin : quart d'heure (fichiers à 15 et 60 min,
    # clé d'origine) ou période de 5 min (fichiers à 5 min).
    mesure_fine = MESURE_5 if pas_minutes == 5 else MESURE_15
    mesures = [l.debut for l in lignes if l.provenance == mesure_fine]
    meta = [
        f"# {FORMAT}",
        f"# version: {version}",
        f"# pas_minutes: {pas_minutes}",
        f"# fuseau: {fuseau}",
        "# unite: kWh",
        "# horodatage: debut de l'intervalle, UTC",
        f"# debut: {iso(lignes[0].debut) if lignes else ''}",
        f"# fin: {iso(lignes[-1].debut + duree_s(lignes[-1], pas_s, version)) if lignes else ''}",
        f"# debut_{mesure_fine}: {iso(min(mesures)) if mesures else 'aucun'}",
        f"# non_configure: {','.join(config.non_configures())}",
        f"# generateur: {generateur}",
        f"# genere_le: {iso(genere_le)}",
    ]
    for c in colonnes:
        meta.append(f"# appareil: {c.nom};categorie={c.categorie}"
                    + (f";inclus_dans={c.inclus_dans}" if c.inclus_dans else ""))
    entete = ["debut_utc", "provenance", *COLONNES_FIXES, *(c.nom for c in colonnes)]
    corps = [",".join(entete)]
    for l in lignes:
        corps.append(",".join([iso(l.debut), l.provenance,
                               *(nombre(l.valeurs.get(c)) for c in COLONNES_FIXES),
                               *(nombre(l.valeurs.get(c.nom)) for c in colonnes)]))
    return "\n".join(meta + corps) + "\n"


def exporter(
    config: Configuration,
    horaires: Mapping[str, Sequence[Mapping]],
    debut: int,
    fin: int,
    pas_minutes: int,
    fuseau: str,
    generateur: str,
    genere_le: int,
    mesures: Mapping[str, Mapping[int, float]] | None = None,
    compact: bool = False,
) -> str:
    """Tout en un : statistiques horaires (format ``statistics_during_period``)
    et, pour le pas de 5 ou 15 min, énergies déjà calculées à ce pas
    (``mesures`` : statistique → début de période → kWh). ``compact`` : version 2
    pour un pas de 5 ou 15 min (le passé reste horaire) ; au pas de 60 min, le
    fichier est le même dans les deux versions : il reste en version 1."""
    if pas_minutes not in PAS_MINUTES:
        raise ValueError("pas de 5, 15 ou 60 minutes seulement")
    debut -= debut % 3600
    fin += -fin % 3600
    energies_h = {s: variations(horaires.get(s, []), 3600) for s in config.statistiques()}
    heures = construire_lignes(config, energies_h, debut, fin, 3600, MESURE_60)
    version = VERSION
    if pas_minutes == 60:
        lignes = heures
    else:
        pas_s = pas_minutes * 60
        mesures = mesures or {}
        instants = [t for par_t in mesures.values() for t in par_t if debut <= t < fin]
        fines: list[Ligne] = []
        if instants:  # seulement la période couverte par des mesures
            a = min(instants)
            fines = construire_lignes(config, mesures, a - a % 3600, max(instants) + pas_s,
                                      pas_s, MESURE_AU_PAS[pas_minutes])
        connues = {l.debut: l for l in fines if l.provenance != TROU}
        if compact:
            version = VERSION_COMPACTE
            lignes = assembler_compact(heures, connues, pas_s)
        else:
            lignes = assembler(heures, connues, pas_s)
    return ecrire(config, lignes, pas_minutes, fuseau, generateur, genere_le, version)


def variations_par_quart(lignes_5min: Mapping[str, Sequence[Mapping]]) -> dict[str, dict[int, float]]:
    """Statistiques de 5 min → énergie par quart d'heure (3 périodes complètes)."""
    return {s: regrouper(variations(l, 300), 300, 900) for s, l in lignes_5min.items()}


def variations_par_cinq(lignes_5min: Mapping[str, Sequence[Mapping]]) -> dict[str, dict[int, float]]:
    """Statistiques de 5 min → énergie par période de 5 min, telle quelle."""
    return {s: variations(l, 300) for s, l in lignes_5min.items()}


__all__ = [
    "Appareil", "Colonne", "Configuration", "Ligne", "CATEGORIES", "COLONNES_FIXES", "PROVENANCES",
    "MESURE_AU_PAS", "PAS_MINUTES", "PROVENANCES_HORAIRES", "appareils_du_tableau", "assembler", "assembler_compact",
    "assembler_quarts", "construire_lignes", "duree_s",
    "depuis_preferences", "ecrire", "exporter", "iso", "nombre", "regrouper", "variations", "variations_par_cinq",
    "variations_par_quart",
]
# === CODE PARTAGE : fin ===
