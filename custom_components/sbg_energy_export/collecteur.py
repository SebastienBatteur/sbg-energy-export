"""Enregistrement local des quarts d'heure, à partir des statistiques de 5 minutes.

Home Assistant garde les statistiques de 5 minutes environ 10 jours
(``purge_keep_days``) et les statistiques horaires pour toujours. Pour avoir un
historique au quart d'heure, il faut donc l'enregistrer au fil de l'eau : c'est
le rôle de ce module. Toutes les 15 minutes (et au démarrage, pour rattraper un
arrêt de moins de ``purge_keep_days``), il additionne les trois périodes de
5 minutes de chaque quart d'heure et ajoute une ligne par statistique dans
``<config>/sbg_energy_export/quarts/quarts_AAAA-MM.csv``.

Le fichier local contient toutes les sources du tableau Énergie (réseau,
solaire, batterie, tous les appareils) avec leurs identifiants : il reste dans
Home Assistant, comme sa propre base de données. Le choix des appareils et
l'anonymisation s'appliquent à l'export.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
import csv
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any

from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.storage import Store

from .const import DELAI_QUART_S, DOMAIN, SOUS_DOSSIER_QUARTS
from .sbg_format import ROLES, appareils_du_tableau, depuis_preferences, variations_par_quart

_LOGGER = logging.getLogger(__name__)
UNITES = {"energy": "kWh"}
QUART = 900
TRANCHE_S = 86400  # une requête par jour de statistiques de 5 min


def utc(secondes: int) -> datetime:
    """Secondes → datetime UTC."""
    return datetime.fromtimestamp(secondes, timezone.utc)


def statistiques_suivies(prefs: Mapping[str, Any] | None) -> set[str]:
    """Toutes les statistiques d'énergie électrique du tableau Énergie."""
    if not prefs:
        return set()
    config = depuis_preferences(prefs, [d["stat_consumption"] for d in appareils_du_tableau(prefs)], {})
    return config.statistiques()


def a_des_sources(prefs: Mapping[str, Any] | None) -> bool:
    """Le tableau Énergie a au moins une source réseau, solaire ou batterie."""
    return bool(prefs) and any(depuis_preferences(prefs, [], {}).roles.get(r) for r in ROLES)  # type: ignore[arg-type]


async def async_statistiques(
    hass: HomeAssistant, ids: set[str], debut: int, fin: int, periode: str
) -> dict[str, list[dict[str, Any]]]:
    """``statistics_during_period`` dans le fil du recorder (jamais dans la boucle)."""
    if not ids or fin <= debut:
        return {}
    resultat = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, utc(debut), utc(fin), ids, periode, UNITES, {"sum"}
    )
    return {s: [dict(l) for l in lignes] for s, lignes in resultat.items()}


def _ecrire_quarts(dossier: Path, lignes: Sequence[tuple[int, str, float]]) -> None:
    """Ajoute des lignes aux fichiers mensuels (fil d'exécution annexe)."""
    dossier.mkdir(parents=True, exist_ok=True)
    par_mois: dict[str, list[tuple[int, str, float]]] = {}
    for ligne in lignes:
        par_mois.setdefault(utc(ligne[0]).strftime("%Y-%m"), []).append(ligne)
    for mois, contenu in par_mois.items():
        chemin = dossier / f"quarts_{mois}.csv"
        nouveau = not chemin.exists()
        with chemin.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            if nouveau:
                w.writerow(["debut_utc", "statistique", "kwh"])
            for t, stat, kwh in contenu:
                w.writerow([utc(t).strftime("%Y-%m-%dT%H:%M:%SZ"), stat, f"{kwh:.6f}"])


def lire_quarts(dossier: Path, ids: Iterable[str], debut: int, fin: int) -> dict[str, dict[int, float]]:
    """Quarts d'heure enregistrés, par statistique (fil d'exécution annexe)."""
    voulus = set(ids)
    sortie: dict[str, dict[int, float]] = {s: {} for s in voulus}
    if not dossier.is_dir():
        return sortie
    for chemin in sorted(dossier.glob("quarts_*.csv")):
        with chemin.open(encoding="utf-8", newline="") as f:
            for ligne in csv.DictReader(f):
                if ligne["statistique"] not in voulus:
                    continue
                t = int(datetime.strptime(ligne["debut_utc"], "%Y-%m-%dT%H:%M:%SZ")
                        .replace(tzinfo=timezone.utc).timestamp())
                if debut <= t < fin:
                    sortie[ligne["statistique"]][t] = float(ligne["kwh"])
    return sortie


class Collecteur:
    """Agrège et enregistre chaque quart d'heure depuis l'installation."""

    def __init__(self, hass: HomeAssistant, dossier: Path) -> None:
        self.hass = hass
        self.dossier = dossier / SOUS_DOSSIER_QUARTS
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.collecteur")
        self._verrou = asyncio.Lock()
        self._arret: Callable[[], None] | None = None
        self._ecouteurs: list[Callable[[], None]] = []
        self.prochain: int | None = None  # début du prochain quart à traiter
        self.premier: int | None = None   # premier quart enregistré

    @callback
    def async_ecouter(self, rappel: Callable[[], None]) -> Callable[[], None]:
        """S'abonner aux mises à jour (capteur)."""
        self._ecouteurs.append(rappel)
        return lambda: self._ecouteurs.remove(rappel)

    async def async_demarrer(self) -> None:
        """Charge l'état et programme un passage toutes les 15 minutes."""
        etat = await self._store.async_load() or {}
        self.prochain = etat.get("prochain")
        self.premier = etat.get("premier")
        self._arret = async_track_utc_time_change(
            self.hass, self._async_tic, minute=[2, 17, 32, 47], second=30
        )

    @callback
    def async_arreter(self) -> None:
        """Annule la programmation."""
        if self._arret:
            self._arret()
            self._arret = None

    async def _async_tic(self, _maintenant: datetime) -> None:
        await self.async_rattraper()

    async def async_rattraper(self, maintenant: float | None = None) -> int:
        """Traite tous les quarts d'heure complets pas encore enregistrés.

        Rend le nombre de quarts traités. Au premier passage, remonte aussi loin
        que les statistiques de 5 min le permettent (``purge_keep_days``).
        """
        async with self._verrou:
            prefs = (await async_get_manager(self.hass)).data
            ids = statistiques_suivies(prefs)
            if not ids:
                return 0
            maintenant = time.time() if maintenant is None else maintenant
            fin = int((maintenant - DELAI_QUART_S) // QUART * QUART)
            if self.prochain is None:
                jours = max(1, int(get_instance(self.hass).keep_days))
                self.prochain = int((maintenant - jours * 86400 + 3600) // 3600 * 3600)
            traites = 0
            while self.prochain < fin:
                bout = min(fin, self.prochain + TRANCHE_S)
                brut = await async_statistiques(self.hass, ids, self.prochain - 300, bout, "5minute")
                quarts = variations_par_quart(brut)
                lignes = sorted(
                    (t, s, v) for s, par_t in quarts.items() for t, v in par_t.items()
                    if self.prochain <= t < bout
                )
                if bout == fin and maintenant - bout < 3600:
                    # Statistiques récentes pas encore compilées (recorder en retard) :
                    # on s'arrête après le dernier quart qui a des données.
                    derniers = [t for t, _, _ in lignes]
                    if not derniers:
                        break
                    bout = max(derniers) + QUART
                    lignes = [l for l in lignes if l[0] < bout]
                if lignes:
                    await self.hass.async_add_executor_job(_ecrire_quarts, self.dossier, lignes)
                    if self.premier is None:
                        self.premier = lignes[0][0]
                traites += (bout - self.prochain) // QUART
                self.prochain = bout
                await self._store.async_save({"prochain": self.prochain, "premier": self.premier})
            for rappel in list(self._ecouteurs):
                rappel()
            return traites

    async def async_lire(self, ids: Iterable[str], debut: int, fin: int) -> dict[str, dict[int, float]]:
        """Quarts d'heure enregistrés entre ``debut`` et ``fin``."""
        return await self.hass.async_add_executor_job(lire_quarts, self.dossier, set(ids), debut, fin)
