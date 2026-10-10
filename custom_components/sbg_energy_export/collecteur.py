# SPDX-License-Identifier: Apache-2.0
"""Enregistrement local des mesures fines, à partir des statistiques de 5 minutes.

Home Assistant garde les statistiques de 5 minutes environ 10 jours
(``purge_keep_days``) et les statistiques horaires pour toujours. Pour avoir un
historique plus fin que l'heure, il faut donc l'enregistrer au fil de l'eau :
c'est le rôle de ce module. Toutes les 15 minutes (et au démarrage, pour
rattraper un arrêt de moins de ``purge_keep_days``), il lit les statistiques de
5 minutes et enregistre (``stockage.py``) :

* par défaut, chaque quart d'heure (somme des trois périodes de 5 min) ;
* avec l'option « pas plus fin : 5 minutes », chaque période de 5 min telle quelle.

Seules les statistiques utiles sont enregistrées : les sources réseau, solaire
et batterie du tableau Énergie, et les appareils choisis par l'utilisateur.

* **Installation** : le premier passage remonte aussi loin que les statistiques
  de 5 minutes existent (~10 jours) ; avec le passé horaire, l'export contient
  donc dès le premier jour tout l'historique en horaire et ~10 jours au pas fin.
* **Appareil ajouté** : enregistré à partir de ce moment, et rattrapé sur les
  ~10 jours où ses statistiques de 5 minutes existent encore. Même chose pour
  toutes les statistiques quand le pas enregistré change.
* **Appareil retiré** : n'est plus enregistré. Ce qui l'a déjà été reste jusqu'à
  la fin de la durée de conservation, sans être exporté : un historique fin ne
  se reconstruit pas, et un appareil décoché par erreur ou remis plus tard
  retrouve ainsi son passé. Rien ne quitte Home Assistant.
* **Mois terminés** compressés ; mois à 5 min de plus de 12 mois regroupés au quart
  d'heure (le pas de 5 min sert à comprendre les comportements, une année suffit) ;
  mois au-delà de la durée de conservation supprimés.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any

from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.storage import Store
from sqlalchemy.exc import SQLAlchemyError

from . import stockage
from .const import (
    ANCIEN_SOUS_DOSSIER_QUARTS,
    CHOIX_AUCUN,
    CHOIX_TOUS,
    CONSERVATION_DEFAUT,
    DELAI_QUART_S,
    DOMAIN,
    OPT_APPAREILS,
    OPT_CHOIX,
    OPT_CINQ_MINUTES,
    OPT_CONSERVATION,
    SOUS_DOSSIER_MESURES,
)
from .sbg_format import ROLES, appareils_du_tableau, depuis_preferences, regrouper, variations_par_cinq

_LOGGER = logging.getLogger(__name__)
UNITES = {"energy": "kWh"}
QUART = 900
TRANCHE_S = 86400  # une requête par jour de statistiques de 5 min


def utc(secondes: int) -> datetime:
    """Secondes → datetime UTC."""
    return datetime.fromtimestamp(secondes, timezone.utc)


def appareils_choisis(prefs: Mapping[str, Any], options: Mapping[str, Any]) -> list[str]:
    """Statistiques des appareils choisis par l'utilisateur (tous, aucun, une sélection)."""
    tous = [d["stat_consumption"] for d in appareils_du_tableau(prefs)]
    choix = options.get(OPT_CHOIX, CHOIX_AUCUN)
    if choix == CHOIX_TOUS:
        return tous
    if choix == CHOIX_AUCUN:
        return []
    voulus = set(options.get(OPT_APPAREILS, []))
    return [s for s in tous if s in voulus]


def statistiques_suivies(prefs: Mapping[str, Any] | None, options: Mapping[str, Any]) -> set[str]:
    """Sources réseau, solaire, batterie du tableau Énergie, et appareils choisis."""
    if not prefs:
        return set()
    return depuis_preferences(prefs, appareils_choisis(prefs, options), {}).statistiques()


def a_des_sources(prefs: Mapping[str, Any] | None) -> bool:
    """Le tableau Énergie a au moins une source réseau, solaire ou batterie."""
    return bool(prefs) and any(depuis_preferences(prefs, [], {}).roles.get(r) for r in ROLES)  # type: ignore[arg-type]


def recorder_pret(hass: HomeAssistant) -> bool:
    """Le recorder peut répondre : base ouverte et fil du recorder en marche.

    ``async_db_ready`` est résolu à vrai une fois la base ouverte et les migrations bloquantes
    terminées (c'est aussi ce qu'attend la dépendance ``recorder`` du manifest avant de charger
    l'intégration), à faux si le recorder n'a pas pu démarrer. ``is_running`` retombe à faux dès
    que le fil du recorder s'arrête, avant qu'il ferme la base : passé ce moment, une requête
    échoue (« cannot schedule new futures after shutdown ») ou, pire, n'échoue pas (base SQLite
    en mémoire rouverte vide, « no such table: statistics_meta »).
    """
    instance = get_instance(hass)
    pret = instance.async_db_ready
    return bool(instance.is_running and pret.done() and not pret.cancelled() and pret.result())


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


def lire_mesures(dossier: Path, ids: Iterable[str], debut: int, fin: int, pas_min: int) -> dict[str, dict[int, float]]:
    """Mesures au pas demandé (fil d'exécution annexe).

    Pas de 15 min : quarts enregistrés, complétés par les quarts reconstitués à
    partir des périodes de 5 min enregistrées (les trois doivent être connues).
    Pas de 5 min : périodes de 5 min enregistrées seulement.
    """
    ids = set(ids)
    if pas_min == 5:
        return stockage.lire(dossier, 5, ids, debut, fin)
    sortie = stockage.lire(dossier, 15, ids, debut, fin)
    for s, par_t in stockage.lire(dossier, 5, ids, debut, fin).items():
        for t, v in regrouper(par_t, 300, QUART).items():
            sortie.setdefault(s, {}).setdefault(t, v)
    return sortie


class Collecteur:
    """Enregistre les mesures fines depuis l'installation."""

    def __init__(self, hass: HomeAssistant, dossier: Path, options: Mapping[str, Any] | None = None) -> None:
        self.hass = hass
        self.racine = dossier
        self.dossier = dossier / SOUS_DOSSIER_MESURES
        self.options = dict(options or {})
        self.pas = 5 if self.options.get(OPT_CINQ_MINUTES) else 15
        self.conservation_ans = int(self.options.get(OPT_CONSERVATION) or CONSERVATION_DEFAUT)
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.collecteur")
        self._verrou = asyncio.Lock()
        self._arret: Callable[[], None] | None = None
        self._arret_ha: Callable[[], None] | None = None  # écoute de l'arrêt de Home Assistant
        self._passage: asyncio.Task[int] | None = None    # passage périodique en cours
        self._ecouteurs: list[Callable[[], None]] = []
        self.prochain: int | None = None  # début de la prochaine période à traiter
        self.premier: int | None = None   # première période enregistrée
        self.suivies: set[str] | None = None    # statistiques enregistrées au dernier passage
        self.pas_enregistre: int | None = None  # pas du dernier passage

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
        if "suivies" in etat:
            self.suivies = set(etat["suivies"])
        if self.prochain is not None:
            self.pas_enregistre = etat.get("pas", 15)  # 0.1.0 : quart d'heure, sans « pas »
        self._arret = async_track_utc_time_change(
            self.hass, self._async_tic, minute=[2, 17, 32, 47], second=30
        )
        self._arret_ha = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_arret_ha)

    @callback
    def async_arreter(self) -> None:
        """Annule la programmation et le passage périodique en cours (déchargement de l'entrée)."""
        if self._arret:
            self._arret()
            self._arret = None
        if self._arret_ha:
            self._arret_ha()
            self._arret_ha = None
        if self._passage and not self._passage.done():
            self._passage.cancel()
        self._passage = None

    @callback
    def _async_arret_ha(self, _evenement: Event) -> None:
        """Home Assistant s'arrête : plus de passage, celui en cours est abandonné (il reprendra
        au démarrage là où l'état enregistré s'est arrêté)."""
        self._arret_ha = None  # écoute à usage unique, déjà retirée par Home Assistant
        self.async_arreter()

    @callback
    def _async_tic(self, _maintenant: datetime) -> None:
        """Passage périodique, en tâche de fond suivie.

        Une tâche lancée directement par le minuteur n'appartient à personne : ni le déchargement
        de l'entrée ni l'arrêt de Home Assistant ne l'annulent, et elle demande encore des
        statistiques au recorder une fois celui-ci fermé (« cannot schedule new futures after
        shutdown »). Celle-ci est annulée par ``async_arreter`` et, en tâche de fond, par Home
        Assistant à son arrêt."""
        if self.hass.is_stopping or (self._passage and not self._passage.done()):
            return
        self._passage = self.hass.async_create_background_task(
            self.async_passage(), f"{DOMAIN}_passage", eager_start=True
        )

    async def async_passage(self) -> int:
        """Un passage en tâche de fond (démarrage, minuteur) : une erreur ne s'en échappe pas.

        L'exception d'une tâche de fond n'est lue par personne : elle ne ressortirait qu'à la
        destruction de la tâche (« Task exception was never retrieved »), un quart d'heure plus
        tard et sans dire ce qu'il advient des mesures. Rien n'est perdu : ``prochain`` et
        ``suivies`` n'avancent qu'après l'écriture des périodes lues, le passage suivant reprend
        donc là où celui-ci s'est arrêté.
        """
        try:
            return await self.async_rattraper()
        except (SQLAlchemyError, RuntimeError) as erreur:
            # RuntimeError : fil d'exécution du recorder fermé, ou connexion à la base pas
            # (ou plus) établie.
            _LOGGER.warning(
                "Statistiques de Home Assistant indisponibles (%s : %s) : mesures fines non "
                "enregistrées à ce passage, nouvel essai au suivant, rien n'est perdu",
                type(erreur).__name__, str(erreur).splitlines()[0] if str(erreur) else "",
            )
        except Exception:  # noqa: BLE001 - tâche de fond : tout est consigné, le passage suivant réessaie
            _LOGGER.exception(
                "Enregistrement des mesures fines interrompu ; nouvel essai au passage suivant"
            )
        return 0

    async def _async_sauver(self) -> None:
        await self._store.async_save({
            "prochain": self.prochain, "premier": self.premier,
            "suivies": sorted(self.suivies or []), "pas": self.pas_enregistre or self.pas,
        })

    async def _async_periodes(
        self, ids: set[str], debut: int, fin: int
    ) -> tuple[dict[str, dict[int, float]], dict[str, dict[int, float]]]:
        """Énergies par période de 5 min et par quart d'heure complet, de ``debut`` à ``fin``."""
        brut = await async_statistiques(self.hass, ids, debut - 300, fin, "5minute")
        cinq = {s: {t: v for t, v in par_t.items() if debut <= t < fin}
                for s, par_t in variations_par_cinq(brut).items()}
        quarts = {s: regrouper(par_t, 300, QUART) for s, par_t in cinq.items()}
        return cinq, quarts

    async def _async_enregistrer(self, cinq: Mapping[str, Mapping[int, float]],
                                 quarts: Mapping[str, Mapping[int, float]], fin: int) -> None:
        """Écrit, au pas choisi, les périodes antérieures à ``fin``."""
        valeurs = cinq if self.pas == 5 else quarts
        retenues = {s: {t: v for t, v in par_t.items() if t < fin} for s, par_t in valeurs.items()}
        retenues = {s: par_t for s, par_t in retenues.items() if par_t}
        if not retenues:
            return
        await self.hass.async_add_executor_job(stockage.enregistrer, self.dossier, self.pas, retenues)
        debut = min(min(par_t) for par_t in retenues.values())
        self.premier = debut if self.premier is None else min(self.premier, debut)

    async def async_rattraper(self, maintenant: float | None = None) -> int:
        """Traite toutes les périodes complètes pas encore enregistrées.

        Rend le nombre de quarts d'heure traités. Au premier passage, remonte
        aussi loin que les statistiques de 5 min le permettent
        (``purge_keep_days``) ; une statistique ajoutée depuis le passage
        précédent (ou toutes, si le pas enregistré change) est rattrapée sur la
        même durée.
        """
        async with self._verrou:
            if self.hass.is_stopping or not recorder_pret(self.hass):
                # Recorder pas encore prêt, arrêté, ou Home Assistant qui s'arrête : rien n'est
                # demandé (ni marqué comme traité), le passage suivant rattrape.
                _LOGGER.debug("Recorder indisponible : passage reporté")
                return 0
            prefs = (await async_get_manager(self.hass)).data
            ids = statistiques_suivies(prefs, self.options)
            if not ids:
                return 0
            ancien = self.racine / ANCIEN_SOUS_DOSSIER_QUARTS
            if await self.hass.async_add_executor_job(ancien.is_dir):
                n = await self.hass.async_add_executor_job(stockage.migrer_ancien, ancien, self.dossier, ids)
                _LOGGER.info("Version 0.1.0 : %s valeurs au quart d'heure reprises dans le stockage actuel", n)
            maintenant = time.time() if maintenant is None else maintenant
            fin = int((maintenant - DELAI_QUART_S) // QUART * QUART)
            jours = max(1, int(get_instance(self.hass).keep_days))
            plus_ancien = int((maintenant - jours * 86400 + 3600) // 3600 * 3600)
            if self.prochain is None:  # installation
                self.prochain = plus_ancien
                nouvelles: set[str] = set()
            elif self.pas_enregistre != self.pas:
                nouvelles = set(ids)
            elif self.suivies is None:  # 0.1.0 : toutes les statistiques étaient enregistrées
                nouvelles = set()
            else:
                nouvelles = ids - self.suivies
            depart = self.prochain

            traites = 0
            while self.prochain < fin:
                bout = min(fin, self.prochain + TRANCHE_S)
                cinq, quarts = await self._async_periodes(ids, self.prochain, bout)
                if bout == fin and maintenant - bout < 3600:
                    # Statistiques récentes pas encore compilées (recorder en retard) :
                    # on s'arrête après le dernier quart complet qui a des données.
                    derniers = [t for par_t in quarts.values() for t in par_t]
                    if not derniers:
                        break
                    bout = max(derniers) + QUART
                await self._async_enregistrer(cinq, quarts, bout)
                traites += (bout - self.prochain) // QUART
                self.prochain = bout
                await self._async_sauver()

            # Statistiques nouvelles : rattrapées tant que leurs 5 min existent.
            t = plus_ancien
            while nouvelles and t < depart:
                bout = min(depart, t + TRANCHE_S)
                cinq, quarts = await self._async_periodes(nouvelles, t, bout)
                await self._async_enregistrer(cinq, quarts, bout)
                t = bout
            self.suivies = set(ids)
            self.pas_enregistre = self.pas
            await self._async_sauver()

            # 5 min pour les 12 derniers mois, puis le quart d'heure, puis suppression selon la
            # conservation choisie (décision du 06/10/2026, même règle que le service).
            await self.hass.async_add_executor_job(
                stockage.entretenir, self.dossier, stockage.mois_de(self.prochain),
                stockage.mois_limite(int(maintenant), self.conservation_ans),
                stockage.mois_limite(int(maintenant), 1),
            )
            for rappel in list(self._ecouteurs):
                rappel()
            return traites

    async def async_lire(self, ids: Iterable[str], debut: int, fin: int, pas_min: int = 15) -> dict[str, dict[int, float]]:
        """Mesures enregistrées entre ``debut`` et ``fin``, au pas de 5 ou 15 min."""
        return await self.hass.async_add_executor_job(lire_mesures, self.dossier, set(ids), debut, fin, pas_min)
