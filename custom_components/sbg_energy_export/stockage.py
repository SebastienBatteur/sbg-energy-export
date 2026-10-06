"""Stockage local des mesures fines (5 ou 15 min), un fichier par mois.

Python pur (bibliothèque standard) : testé sans Home Assistant, appelé dans un
fil d'exécution annexe (jamais dans la boucle de Home Assistant).

Fichiers, dans ``<config>/sbg_energy_export/mesures/`` :

* ``mesures_15min_AAAA-MM.csv`` (ou ``mesures_5min_...``) pour le mois en cours,
  en clair, complété au fil de l'eau par simple ajout de lignes ;
* ``mesures_15min_AAAA-MM.csv.gz`` pour chaque mois terminé, compressé (gzip,
  sans date ni nom dans l'en-tête gzip : deux compressions du même mois donnent
  le même fichier).

Contenu : une ligne par période, une colonne par statistique (forme « large »,
bien plus compacte qu'une ligne par statistique, surtout une fois compressée) ::

    debut_utc,sensor.borne,sensor.import,...
    2026-10-06T08:15:00Z,0.25,0.012,...

kWh sur la période, 6 décimales au plus ; cellule vide = inconnu. Les mois sont
des mois UTC. Les colonnes d'un mois sont toutes les statistiques enregistrées
pendant ce mois : une statistique ajoutée en cours de mois fait réécrire le
fichier du mois une fois avec la nouvelle colonne.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import csv
from datetime import datetime, timezone
import gzip
import io
import logging
import os
from pathlib import Path
import re

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
PREMIERE_COLONNE = "debut_utc"
NOM = re.compile(r"^mesures_(5|15)min_(\d{4}-\d{2})\.csv(\.gz)?$")

Valeurs = Mapping[str, Mapping[int, float]]


def mois_de(t: int) -> str:
    """``AAAA-MM`` (UTC) de l'instant ``t``."""
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m")


def chemin(dossier: Path, pas_min: int, mois: str, compresse: bool) -> Path:
    """Chemin du fichier d'un mois."""
    return dossier / f"mesures_{pas_min}min_{mois}.csv{'.gz' if compresse else ''}"


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _kwh(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


# ------------------------------------------------------------------ fichiers
def lire_fichier(f: Path) -> tuple[list[str], dict[int, dict[str, float]]]:
    """Colonnes (statistiques) et valeurs d'un fichier mensuel, clair ou compressé."""
    if f.suffix == ".gz":
        texte = gzip.decompress(f.read_bytes()).decode("utf-8")
    else:
        texte = f.read_text(encoding="utf-8")
    lecteur = csv.reader(io.StringIO(texte))
    entete = next(lecteur, None)
    if not entete or entete[0] != PREMIERE_COLONNE:
        raise ValueError(f"{f.name} : en-tête inattendu")
    colonnes = entete[1:]
    lignes: dict[int, dict[str, float]] = {}
    for ligne in lecteur:
        if not ligne:
            continue
        valeurs = lignes.setdefault(_instant(ligne[0]), {})
        for stat, cellule in zip(colonnes, ligne[1:], strict=False):
            if cellule != "":
                valeurs[stat] = float(cellule)
    return colonnes, lignes


def _texte(colonnes: list[str], lignes: Mapping[int, Mapping[str, float]]) -> str:
    sortie = io.StringIO()
    w = csv.writer(sortie, lineterminator="\n")
    w.writerow([PREMIERE_COLONNE, *colonnes])
    for t in sorted(lignes):
        w.writerow([_iso(t), *(_kwh(lignes[t].get(c)) for c in colonnes)])
    return sortie.getvalue()


def _remplacer(f: Path, contenu: bytes) -> None:
    """Écriture atomique : fichier temporaire, puis remplacement."""
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_bytes(contenu)
    os.replace(tmp, f)


def _compresser(texte: str) -> bytes:
    tampon = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=tampon, compresslevel=9, mtime=0) as g:
        g.write(texte.encode("utf-8"))
    return tampon.getvalue()


def ecrire_fichier(f: Path, colonnes: list[str], lignes: Mapping[int, Mapping[str, float]]) -> None:
    """Réécrit tout le fichier (compressé si son nom finit par ``.gz``)."""
    texte = _texte(colonnes, lignes)
    _remplacer(f, _compresser(texte) if f.suffix == ".gz" else texte.encode("utf-8"))


def _derniere_ligne(f: Path) -> tuple[list[str], int | None]:
    """En-tête et dernier instant d'un fichier en clair, sans tout lire."""
    with f.open("rb") as h:
        entete = h.readline().decode("utf-8").rstrip("\n").split(",")
        taille = h.seek(0, os.SEEK_END)
        h.seek(max(0, taille - 4096))
        fin = h.read().decode("utf-8", errors="replace").rstrip("\n").rsplit("\n", 1)[-1]
    premier = fin.split(",", 1)[0]
    return entete[1:], (None if premier == PREMIERE_COLONNE else _instant(premier))


# ------------------------------------------------------------------ écriture
def enregistrer(dossier: Path, pas_min: int, valeurs: Valeurs) -> None:
    """Ajoute des mesures (statistique → début de période → kWh).

    Cas courant (toutes les 15 min) : les périodes suivent la fin du fichier du
    mois en cours et ses colonnes suffisent → simple ajout de lignes, sans
    réécrire le fichier. Sinon (rattrapage d'une statistique ajoutée, mois déjà
    compressé, nouvelle colonne) : fusion et réécriture du mois ; une nouvelle
    valeur remplace l'ancienne pour la même période.
    """
    par_mois: dict[str, dict[int, dict[str, float]]] = {}
    for stat, par_t in valeurs.items():
        for t, v in par_t.items():
            par_mois.setdefault(mois_de(t), {}).setdefault(t, {})[stat] = v
    if not par_mois:
        return
    dossier.mkdir(parents=True, exist_ok=True)
    for mois, nouvelles in sorted(par_mois.items()):
        stats = sorted({s for v in nouvelles.values() for s in v})
        gz = chemin(dossier, pas_min, mois, True)
        clair = chemin(dossier, pas_min, mois, False)
        if not gz.exists() and clair.exists():
            colonnes, dernier = _derniere_ligne(clair)
            if set(stats) <= set(colonnes) and (dernier is None or min(nouvelles) > dernier):
                texte = _texte(colonnes, nouvelles).split("\n", 1)[1]
                with clair.open("a", encoding="utf-8", newline="") as h:
                    h.write(texte)
                continue
        cible = gz if gz.exists() else clair
        colonnes, lignes = lire_fichier(cible) if cible.exists() else ([], {})
        for t, vals in nouvelles.items():
            lignes.setdefault(t, {}).update(vals)
        ecrire_fichier(cible, sorted(set(colonnes) | set(stats)), lignes)


# ------------------------------------------------------------------ lecture
def fichiers(dossier: Path) -> list[tuple[int, str, bool, Path]]:
    """(pas, mois, compressé, chemin) de chaque fichier mensuel."""
    if not dossier.is_dir():
        return []
    sortie = []
    for f in dossier.iterdir():
        m = NOM.match(f.name)
        if m:
            sortie.append((int(m.group(1)), m.group(2), bool(m.group(3)), f))
    return sorted(sortie, key=lambda x: (x[0], x[1], x[2]))


def lire(dossier: Path, pas_min: int, ids: Iterable[str], debut: int, fin: int) -> dict[str, dict[int, float]]:
    """Mesures enregistrées au pas ``pas_min``, de ``debut`` (inclus) à ``fin`` (exclu)."""
    voulus = set(ids)
    sortie: dict[str, dict[int, float]] = {s: {} for s in voulus}
    m_debut, m_fin = mois_de(debut), mois_de(max(debut, fin - 1))
    for pas, mois, _gz, f in fichiers(dossier):
        if pas != pas_min or not m_debut <= mois <= m_fin:
            continue
        try:
            _colonnes, lignes = lire_fichier(f)
        except (OSError, EOFError, ValueError, gzip.BadGzipFile) as err:
            _LOGGER.warning("Fichier de mesures illisible, ignoré : %s (%s)", f.name, err)
            continue
        for t, v in lignes.items():
            if debut <= t < fin:
                for stat in voulus.intersection(v):
                    sortie[stat][t] = v[stat]
    return sortie


# ------------------------------------------------------------------ entretien
def mois_limite(maintenant: int, ans: int) -> str:
    """Premier mois gardé : celui d'il y a ``ans`` années (mois UTC)."""
    d = datetime.fromtimestamp(maintenant, UTC)
    return f"{d.year - ans:04d}-{d.month:02d}"


def entretenir(dossier: Path, mois_ouvert: str, premier_garde: str) -> tuple[int, int]:
    """Compresse les mois terminés (avant ``mois_ouvert``) et supprime ceux
    d'avant ``premier_garde``. Rend (nombre compressés, nombre supprimés)."""
    compresses = supprimes = 0
    for pas, mois, gz, f in fichiers(dossier):
        if mois < premier_garde:
            f.unlink(missing_ok=True)
            supprimes += 1
        elif not gz and mois < mois_ouvert:
            cible = chemin(dossier, pas, mois, True)
            colonnes, lignes = lire_fichier(f)
            if cible.exists():  # arrêt pendant une compression précédente : on fusionne
                anciennes, deja = lire_fichier(cible)
                for t, v in lignes.items():
                    deja.setdefault(t, {}).update(v)
                colonnes, lignes = sorted(set(anciennes) | set(colonnes)), deja
            ecrire_fichier(cible, colonnes, lignes)
            f.unlink()
            compresses += 1
    for tmp in dossier.glob("*.tmp") if dossier.is_dir() else []:
        tmp.unlink(missing_ok=True)
    return compresses, supprimes


def migrer_ancien(ancien: Path, dossier: Path, ids: Iterable[str]) -> int:
    """Version 0.1.0 : ``quarts/quarts_AAAA-MM.csv`` (une ligne par quart et par
    statistique, toutes les statistiques du tableau). Convertit les quarts des
    statistiques suivies vers le stockage actuel au pas de 15 min, puis supprime
    les anciens fichiers. Rend le nombre de valeurs reprises."""
    if not ancien.is_dir():
        return 0
    voulus = set(ids)
    n = 0
    for f in sorted(ancien.glob("quarts_*.csv")):
        valeurs: dict[str, dict[int, float]] = {}
        with f.open(encoding="utf-8", newline="") as h:
            for ligne in csv.DictReader(h):
                if ligne.get("statistique") in voulus:
                    valeurs.setdefault(ligne["statistique"], {})[_instant(ligne["debut_utc"])] = float(ligne["kwh"])
                    n += 1
        enregistrer(dossier, 15, valeurs)
        f.unlink()
    try:
        ancien.rmdir()
    except OSError:
        pass
    return n
