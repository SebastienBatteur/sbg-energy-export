#!/usr/bin/env python3
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
Licence : voir LICENSE du dépôt sbg-ha-export.
"""
from __future__ import annotations

# === CODE PARTAGE : debut (copie identique dans outils/sbg_ha_export.py) ===
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

FORMAT = "SBG HA export"
VERSION = 1

# Colonnes d'énergie fixes, dans l'ordre du fichier.
PRELEVEMENT = "prelevement_reseau"
INJECTION = "injection_reseau"
SOLAIRE = "production_solaire"
CHARGE = "charge_batterie"
DECHARGE = "decharge_batterie"
CONSO = "consommation_maison"
ROLES: tuple[str, ...] = (PRELEVEMENT, INJECTION, SOLAIRE, CHARGE, DECHARGE)
COLONNES_FIXES: tuple[str, ...] = (*ROLES, CONSO)

CATEGORIES: tuple[str, ...] = ("voiture", "pac", "ballon", "cuisson", "autre")

MESURE_15 = "mesure_15min"
MESURE_60 = "mesure_60min"
HEURE_REPARTIE = "heure_repartie"
TROU = "trou"
PROVENANCES: tuple[str, ...] = (MESURE_15, MESURE_60, HEURE_REPARTIE, TROU)

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


def assembler_quarts(heures: Sequence[Ligne], quarts: Mapping[int, Ligne]) -> list[Ligne]:
    """Fichier au quart d'heure : quarts mesurés, sinon heure répartie en 4.

    Pour chaque heure : si au moins un quart est mesuré, les 4 quarts viennent
    des mesures (les quarts manquants sont des trous) ; sinon l'heure est
    répartie en 4 parts égales (provenance « heure_repartie ») ; une heure
    inconnue donne 4 trous.
    """
    sortie: list[Ligne] = []
    for h in heures:
        qs = [quarts.get(h.debut + 900 * k) for k in range(4)]
        if any(q is not None and q.provenance != TROU for q in qs):
            for k, q in enumerate(qs):
                sortie.append(q if q is not None else Ligne(h.debut + 900 * k, TROU, {c: None for c in h.valeurs}))
        elif h.provenance == TROU:
            sortie.extend(Ligne(h.debut + 900 * k, TROU, dict(h.valeurs)) for k in range(4))
        else:
            quart = {c: (None if v is None else v / 4.0) for c, v in h.valeurs.items()}
            sortie.extend(Ligne(h.debut + 900 * k, HEURE_REPARTIE, dict(quart)) for k in range(4))
    return sortie


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
) -> str:
    """Texte complet du fichier (UTF-8, fin de ligne LF, séparateur virgule)."""
    if pas_minutes not in (15, 60):
        raise ValueError("pas de 15 ou 60 minutes seulement")
    colonnes = config.colonnes()
    pas_s = pas_minutes * 60
    quarts = [l.debut for l in lignes if l.provenance == MESURE_15]
    meta = [
        f"# {FORMAT}",
        f"# version: {VERSION}",
        f"# pas_minutes: {pas_minutes}",
        f"# fuseau: {fuseau}",
        "# unite: kWh",
        "# horodatage: debut de l'intervalle, UTC",
        f"# debut: {iso(lignes[0].debut) if lignes else ''}",
        f"# fin: {iso(lignes[-1].debut + pas_s) if lignes else ''}",
        f"# debut_mesure_15min: {iso(min(quarts)) if quarts else 'aucun'}",
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
    quarts: Mapping[str, Mapping[int, float]] | None = None,
) -> str:
    """Tout en un : statistiques horaires (format ``statistics_during_period``)
    et, pour le pas de 15 min, énergies au quart d'heure déjà calculées."""
    debut -= debut % 3600
    fin += -fin % 3600
    energies_h = {s: variations(horaires.get(s, []), 3600) for s in config.statistiques()}
    heures = construire_lignes(config, energies_h, debut, fin, 3600, MESURE_60)
    if pas_minutes == 60:
        lignes = heures
    else:
        q = construire_lignes(config, quarts or {}, debut, fin, 900, MESURE_15)
        lignes = assembler_quarts(heures, {l.debut: l for l in q if l.provenance != TROU})
    return ecrire(config, lignes, pas_minutes, fuseau, generateur, genere_le)


def variations_par_quart(lignes_5min: Mapping[str, Sequence[Mapping]]) -> dict[str, dict[int, float]]:
    """Statistiques de 5 min → énergie par quart d'heure (3 périodes complètes)."""
    return {s: regrouper(variations(l, 300), 300, 900) for s, l in lignes_5min.items()}


__all__ = [
    "Appareil", "Colonne", "Configuration", "Ligne", "CATEGORIES", "COLONNES_FIXES", "PROVENANCES",
    "appareils_du_tableau", "assembler_quarts", "construire_lignes", "depuis_preferences", "ecrire",
    "exporter", "iso", "nombre", "regrouper", "variations", "variations_par_quart",
]
# === CODE PARTAGE : fin ===

# ======================================================================
# Script : lecture des statistiques et écriture du fichier.
# ======================================================================
import argparse
import base64
import csv
import getpass
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.parse

VERSION_SCRIPT = "0.1.0"
NOMS_ROLES = {
    "prelevement": PRELEVEMENT, "injection": INJECTION, "solaire": SOLAIRE,
    "charge": CHARGE, "decharge": DECHARGE,
}
# Types de lignes du fichier « energy.csv » du tableau Énergie → rôles.
TYPES_CSV_ENERGIE = {
    "grid_consumption": PRELEVEMENT, "grid_return": INJECTION, "solar_production": SOLAIRE,
    "battery_in": CHARGE, "battery_out": DECHARGE,
}


class WebSocketMinimal:
    """Client WebSocket (RFC 6455) réduit au strict nécessaire, sans dépendance.

    Il ne parle qu'à l'adresse de Home Assistant donnée par l'utilisateur.
    """

    def __init__(self, url: str, verifier_tls: bool = True, delai: float = 120.0) -> None:
        u = urllib.parse.urlparse(url)
        securise = u.scheme in ("https", "wss")
        port = u.port or (443 if securise else 80)
        brut = socket.create_connection((u.hostname, port), timeout=delai)
        if securise:
            ctx = ssl.create_default_context()
            if not verifier_tls:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            brut = ctx.wrap_socket(brut, server_hostname=u.hostname)
        self.sock = brut
        cle = base64.b64encode(os.urandom(16)).decode()
        chemin = (u.path.rstrip("/") or "") + "/api/websocket"
        requete = (f"GET {chemin} HTTP/1.1\r\nHost: {u.hostname}:{port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {cle}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(requete.encode())
        reponse = b""
        while b"\r\n\r\n" not in reponse:
            morceau = self.sock.recv(4096)
            if not morceau:
                raise ConnectionError("connexion fermée pendant la poignée de main")
            reponse += morceau
        entete, self.tampon = reponse.split(b"\r\n\r\n", 1)
        if b" 101 " not in entete.split(b"\r\n", 1)[0]:
            raise ConnectionError("Home Assistant refuse la connexion WebSocket : "
                                  + entete.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.n = 0

    def _lire(self, n: int) -> bytes:
        while len(self.tampon) < n:
            morceau = self.sock.recv(max(65536, n - len(self.tampon)))
            if not morceau:
                raise ConnectionError("connexion fermée")
            self.tampon += morceau
        d, self.tampon = self.tampon[:n], self.tampon[n:]
        return d

    def _trame(self, opcode: int, donnees: bytes) -> None:
        masque = os.urandom(4)
        n = len(donnees)
        if n < 126:
            entete = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            entete = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            entete = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        masquees = bytes(b ^ masque[i % 4] for i, b in enumerate(donnees))
        self.sock.sendall(entete + masque + masquees)

    def envoyer(self, message: dict) -> None:
        self._trame(0x1, json.dumps(message).encode())

    def recevoir(self) -> dict:
        morceaux = []
        while True:
            b1, b2 = self._lire(2)
            fin, opcode, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._lire(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._lire(8))[0]
            masque = self._lire(4) if b2 & 0x80 else None
            donnees = self._lire(n)
            if masque:
                donnees = bytes(b ^ masque[i % 4] for i, b in enumerate(donnees))
            if opcode == 0x9:  # ping
                self._trame(0xA, donnees)
                continue
            if opcode == 0x8:
                raise ConnectionError("Home Assistant a fermé la connexion")
            if opcode in (0x0, 0x1, 0x2):
                morceaux.append(donnees)
                if fin:
                    return json.loads(b"".join(morceaux))

    def commande(self, message: dict) -> object:
        self.n += 1
        self.envoyer({"id": self.n, **message})
        while True:
            r = self.recevoir()
            if r.get("id") == self.n and r.get("type") == "result":
                if not r.get("success"):
                    raise RuntimeError(f"{message['type']} : {r.get('error')}")
                return r.get("result")

    def fermer(self) -> None:
        try:
            self._trame(0x8, b"")
            self.sock.close()
        except OSError:
            pass


def connecter(url: str, jeton: str, verifier_tls: bool) -> WebSocketMinimal:
    ws = WebSocketMinimal(url, verifier_tls)
    if ws.recevoir().get("type") != "auth_required":
        raise ConnectionError("réponse inattendue de Home Assistant")
    ws.envoyer({"type": "auth", "access_token": jeton})
    r = ws.recevoir()
    if r.get("type") != "auth_ok":
        raise PermissionError("jeton refusé par Home Assistant")
    return ws


def statistiques(ws: WebSocketMinimal, ids: set, debut: int, fin: int, periode: str,
                 tranche_s: int) -> dict:
    """``recorder/statistics_during_period`` par tranches (messages raisonnables)."""
    sortie: dict = {s: [] for s in ids}
    t = debut
    while t < fin:
        u = min(fin, t + tranche_s)
        r = ws.commande({
            "type": "recorder/statistics_during_period", "start_time": iso(t), "end_time": iso(u),
            "statistic_ids": sorted(ids), "period": periode, "units": {"energy": "kWh"},
            "types": ["sum"],
        }) or {}
        for s, lignes in r.items():
            sortie.setdefault(s, []).extend(lignes)
        t = u
        print(f"  {periode} : {iso(t)[:10]}", end="\r", file=sys.stderr)
    print(file=sys.stderr)
    return sortie


def debut_des_statistiques(ws: WebSocketMinimal, ids: set, fin: int) -> int:
    """Premier mois qui a des statistiques (requête mensuelle, légère)."""
    r = ws.commande({"type": "recorder/statistics_during_period", "start_time": "2000-01-01T00:00:00Z",
                     "end_time": iso(fin), "statistic_ids": sorted(ids), "period": "month",
                     "types": ["sum"]}) or {}
    debuts = [en_secondes(l["start"]) for lignes in r.values() for l in lignes]
    return min(debuts) if debuts else fin - 86400


def demander_appareils(prefs: dict, choix: str | None, categories_args: dict) -> tuple[list, dict]:
    """Choix des appareils : tous, aucun ou une sélection ; catégorie de chacun."""
    appareils = appareils_du_tableau(prefs)
    if not appareils:
        return [], {}
    print("\nAppareils suivis dans votre tableau Énergie (ces noms restent chez vous) :")
    for i, a in enumerate(appareils, 1):
        print(f"  {i}. {a.get('name') or a['stat_consumption']}")
    if choix is None:
        choix = input("Exporter quels appareils ? « tous », « aucun » ou leurs numéros (ex. 1,3) : ").strip()
    if choix.lower() == "aucun":
        return [], {}
    if choix.lower() == "tous":
        rangs = list(range(1, len(appareils) + 1))
    else:
        rangs = [int(x) for x in choix.replace(" ", "").split(",") if x]
    choisis, categories = [], {}
    for r in rangs:
        stat = appareils[r - 1]["stat_consumption"]
        cat = categories_args.get(str(r))
        while cat not in CATEGORIES:
            cat = input(f"Catégorie de l'appareil {r} ({', '.join(CATEGORIES)}) : ").strip().lower()
        choisis.append(stat)
        categories[stat] = cat
    return choisis, categories


def lire_csv_energie(chemins: list) -> tuple[dict, dict]:
    """Fichiers « energy.csv » téléchargés depuis le tableau Énergie.

    Une ligne par statistique, une colonne par période (début, UTC). Seules les
    vues d'au plus 3 jours sont horaires : on n'accepte que des colonnes d'une heure.
    Rendu : (énergies par statistique et par heure, types des statistiques).
    """
    energies: dict = {}
    types: dict = {}
    for chemin in chemins:
        with open(chemin, encoding="utf-8-sig", newline="") as f:
            lignes = list(csv.reader(f))
        temps = [en_secondes(t) for t in lignes[0][3:]]
        ecarts = {b - a for a, b in zip(temps, temps[1:])}
        if ecarts - {3600}:
            raise ValueError(f"{chemin} : périodes non horaires ({sorted(ecarts)[:3]} s) ; "
                             "téléchargez des vues d'au plus 3 jours")
        for ligne in lignes[1:]:
            stat, typ = ligne[0], ligne[1]
            if not stat or not (typ in TYPES_CSV_ENERGIE or typ == "device_consumption"):
                continue
            types[stat] = typ
            for t, cellule in zip(temps, ligne[3:]):
                if cellule != "":
                    energies.setdefault(stat, {})[t] = float(cellule)
    return energies, types


def principal(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Export « SBG HA export » des données du tableau Énergie de Home Assistant. "
                                            "Rien n'est envoyé ailleurs qu'à votre propre Home Assistant.")
    p.add_argument("--url", help="adresse de Home Assistant, ex. http://homeassistant.local:8123")
    p.add_argument("--certificat-non-verifie", action="store_true",
                   help="accepter un certificat HTTPS auto-signé (réseau local seulement)")
    p.add_argument("--depuis-json", help="fichier JSON au format recorder/statistics_during_period (période heure)")
    p.add_argument("--depuis-csv", nargs="+",
                   help="fichiers energy.csv téléchargés du tableau Énergie (vues de 1 à 3 jours)")
    p.add_argument("--role", action="append", default=[],
                   help="avec --depuis-json : prelevement=sensor.x (aussi injection, solaire, charge, decharge)")
    p.add_argument("--appareil", action="append", default=[],
                   help="avec --depuis-json ou --depuis-csv : sensor.x=voiture (pac, ballon, cuisson, autre)")
    p.add_argument("--appareils", help="avec --url : tous, aucun, ou numéros 1,3")
    p.add_argument("--categorie", action="append", default=[], help="avec --url : 1=voiture")
    p.add_argument("--pas", type=int, choices=(15, 60), default=60)
    p.add_argument("--debut", help="AAAA-MM-JJ (UTC), par défaut le début des statistiques")
    p.add_argument("--fin", help="AAAA-MM-JJ (UTC, exclu), par défaut l'heure en cours")
    p.add_argument("--fuseau", default=None,
                   help="fuseau de la maison (par défaut celui de Home Assistant, sinon Europe/Brussels)")
    p.add_argument("--sortie", default="sbg_ha_export.csv")
    a = p.parse_args(argv)

    maintenant = int(time.time())
    fin = en_secondes(a.fin + "T00:00:00Z") if a.fin else maintenant - maintenant % 3600
    debut = en_secondes(a.debut + "T00:00:00Z") if a.debut else None
    fuseau = a.fuseau or "Europe/Brussels"
    quarts = None
    generateur = f"sbg_ha_export.py {VERSION_SCRIPT}"

    if a.url:
        jeton = os.environ.get("SBG_HA_JETON") or getpass.getpass("Jeton d'accès longue durée (non affiché) : ")
        ws = connecter(a.url, jeton.strip(), not a.certificat_non_verifie)
        del jeton
        try:
            fuseau = a.fuseau or (ws.commande({"type": "get_config"}) or {}).get("time_zone") or fuseau
            prefs = ws.commande({"type": "energy/get_prefs"}) or {}
            cats = dict(c.split("=", 1) for c in a.categorie)
            choisis, categories = demander_appareils(prefs, a.appareils, cats)
            config = depuis_preferences(prefs, choisis, categories)
            ids = config.statistiques()
            if not config.roles:
                print("Aucune source réseau, solaire ou batterie dans le tableau Énergie.", file=sys.stderr)
                return 2
            if debut is None:
                debut = debut_des_statistiques(ws, ids, fin)
            horaires = statistiques(ws, ids, debut - 3600, fin, "hour", 31 * 86400)
            if not a.debut:  # la première ligne de statistiques sert de référence
                debuts = [en_secondes(l["start"]) for lignes in horaires.values() for l in lignes]
                debut = min(debuts) + 3600 if debuts else debut
            if a.pas == 15:
                cinq = statistiques(ws, ids, max(debut, fin - 12 * 86400) - 300, fin, "5minute", 86400)
                quarts = variations_par_quart(cinq)
        finally:
            ws.fermer()
    elif a.depuis_json or a.depuis_csv:
        appareils = [x.split("=", 1) for x in a.appareil]
        if a.depuis_json:
            with open(a.depuis_json, encoding="utf-8") as f:
                horaires = json.load(f)
            roles: dict = {}
            for x in a.role:
                nom, stat = x.split("=", 1)
                roles.setdefault(NOMS_ROLES[nom], []).append(stat)
        else:
            energies, types = lire_csv_energie(a.depuis_csv)
            roles = {}
            for stat, typ in types.items():
                if typ in TYPES_CSV_ENERGIE:
                    roles.setdefault(TYPES_CSV_ENERGIE[typ], []).append(stat)
            # Énergies déjà par heure : on reconstitue des « sum » cumulés.
            horaires = {stat: _cumuls(par_heure) for stat, par_heure in energies.items()}
        config = Configuration(roles, [Appareil(s, c) for s, c in appareils])
        config.colonnes()  # refuse une catégorie inconnue
        if debut is None:
            debuts = [en_secondes(l["start"]) for s in config.statistiques() for l in horaires.get(s, [])]
            debut = min(debuts) + 3600 if debuts else fin  # la première ligne sert de référence
        if not a.fin:
            fins = [en_secondes(l["start"]) + 3600 for s in config.statistiques() for l in horaires.get(s, [])]
            fin = max(fins) if fins else fin
    else:
        p.error("donnez --url, --depuis-json ou --depuis-csv")
        return 2

    texte = exporter(config, horaires, debut, fin, a.pas, fuseau, generateur, maintenant, quarts)
    with open(a.sortie, "w", encoding="utf-8", newline="\n") as f:
        f.write(texte)
    lignes = texte.count("\n") - texte.count("\n#") - 2
    print(f"Écrit : {a.sortie} ({lignes} lignes au pas de {a.pas} min, de {iso(debut)} à {iso(fin)}).")
    print("Déposez-le vous-même sur analyse.sbg-energy.com. Le script n'a rien envoyé d'autre part.")
    return 0


def _cumuls(par_heure: dict) -> list:
    """Énergies horaires → lignes « sum » consécutives (une heure sans valeur coupe la suite)."""
    lignes = []
    cumul = 0.0
    precedent = None
    for t in sorted(par_heure):
        if precedent is None or precedent + 3600 != t:
            lignes.append({"start": t - 3600, "sum": cumul})
        cumul += par_heure[t]
        lignes.append({"start": t, "sum": cumul})
        precedent = t
    return lignes


if __name__ == "__main__":
    sys.exit(principal())
