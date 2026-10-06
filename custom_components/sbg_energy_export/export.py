# SPDX-License-Identifier: Apache-2.0
"""Production du fichier « SBG HA export » et lien de téléchargement local.

Le passé vient des statistiques à long terme (horaires, gardées pour toujours) ;
le pas fin (15 min, ou 5 min si l'option est choisie) vient des
enregistrements du collecteur : ~10 jours avant l'installation, puis en continu. Le fichier est écrit dans
``<config>/sbg_energy_export/exports/`` et se télécharge par un lien signé,
servi par Home Assistant lui-même et valable une heure. Rien n'est envoyé
ailleurs : l'utilisateur dépose le fichier lui-même sur analyse.sbg-energy.com.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
import re
import time
from typing import Any

from aiohttp import web
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.http import KEY_HASS

from .collecteur import Collecteur, appareils_choisis, async_statistiques
from .const import (
    DOMAIN,
    OPT_CATEGORIES,
    OPT_CINQ_MINUTES,
    SOUS_DOSSIER_EXPORTS,
    VALIDITE_LIEN_H,
    VERSION,
)
from .sbg_format import depuis_preferences, en_secondes, exporter

URL_FICHIER = f"/api/{DOMAIN}/fichier"
NOM_VALIDE = re.compile(r"^sbg_ha_export_\d{8}-\d{6}_(5|15|60)min\.csv$")
MOIS_S = 31 * 86400


@dataclass
class Resultat:
    """Ce que rend un export."""

    chemin: Path
    lien: str
    lignes: int
    debut: str
    fin: str


async def async_premier_instant(hass: HomeAssistant, ids: set[str], fin: int) -> int:
    """Première heure exportable : celle qui suit la première ligne de statistiques
    (la première ligne n'a pas de référence pour calculer son énergie). Une requête
    mensuelle trouve le premier mois, une requête horaire la première heure."""
    debut = int(datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp())
    mois = await async_statistiques(hass, ids, debut, fin, "month")
    debuts = [en_secondes(l["start"]) for lignes in mois.values() for l in lignes]
    if not debuts:
        return fin - 86400
    heures = await async_statistiques(hass, ids, min(debuts), min(fin, min(debuts) + MOIS_S + 86400), "hour")
    debuts = [en_secondes(l["start"]) for lignes in heures.values() for l in lignes]
    return min(debuts) + 3600 if debuts else fin - 86400


async def async_exporter(
    hass: HomeAssistant,
    options: dict[str, Any],
    collecteur: Collecteur,
    dossier: Path,
    pas: int = 15,
    debut: date | None = None,
    fin: date | None = None,
) -> Resultat:
    """Écrit le fichier et rend son chemin et un lien de téléchargement signé."""
    if pas == 5 and not options.get(OPT_CINQ_MINUTES):
        raise HomeAssistantError("Le pas de 5 minutes demande l'option « pas plus fin : 5 minutes ».")
    prefs = (await async_get_manager(hass)).data
    if not prefs:
        raise HomeAssistantError("Le tableau Énergie n'est pas configuré.")
    config = depuis_preferences(prefs, appareils_choisis(prefs, options), options.get(OPT_CATEGORIES, {}))
    if not config.roles:
        raise HomeAssistantError("Le tableau Énergie n'a ni réseau, ni solaire, ni batterie.")
    ids = config.statistiques()
    maintenant = int(time.time())
    t_fin = _jour(fin) if fin else maintenant - maintenant % 3600
    t_debut = _jour(debut) if debut else await async_premier_instant(hass, ids, t_fin)
    if t_fin <= t_debut:
        raise HomeAssistantError("La fin doit suivre le début.")
    if pas != 60:
        await collecteur.async_rattraper()
    horaires: dict[str, list[dict[str, Any]]] = {s: [] for s in ids}
    t = t_debut - 3600  # la ligne qui précède donne l'énergie de la première heure
    while t < t_fin:
        bout = min(t_fin, t + MOIS_S)
        for s, lignes in (await async_statistiques(hass, ids, t, bout, "hour")).items():
            horaires.setdefault(s, []).extend(lignes)
        t = bout
    mesures = await collecteur.async_lire(ids, t_debut, t_fin, pas) if pas != 60 else None
    texte = await hass.async_add_executor_job(
        exporter, config, horaires, t_debut, t_fin, pas, str(hass.config.time_zone),
        f"{DOMAIN} {VERSION}", maintenant, mesures,
    )
    nom = f"sbg_ha_export_{datetime.fromtimestamp(maintenant, timezone.utc):%Y%m%d-%H%M%S}_{pas}min.csv"
    chemin = dossier / SOUS_DOSSIER_EXPORTS / nom
    await hass.async_add_executor_job(_ecrire, chemin, texte)
    lien = async_sign_path(hass, f"{URL_FICHIER}/{nom}", timedelta(hours=VALIDITE_LIEN_H))
    corps = [l for l in texte.splitlines() if not l.startswith("#")]
    return Resultat(chemin, lien, len(corps) - 1, corps[1][:20] if len(corps) > 1 else "",
                    corps[-1][:20] if len(corps) > 1 else "")


def _jour(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _ecrire(chemin: Path, texte: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8", newline="\n")


class VueFichier(HomeAssistantView):
    """Téléchargement d'un export (utilisateur connecté ou lien signé)."""

    url = URL_FICHIER + "/{nom}"
    name = f"api:{DOMAIN}:fichier"
    requires_auth = True

    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier / SOUS_DOSSIER_EXPORTS

    async def get(self, request: web.Request, nom: str) -> web.StreamResponse:
        """Sert le fichier demandé, s'il a bien un nom d'export."""
        if not NOM_VALIDE.match(nom):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        chemin = self.dossier / nom
        hass = request.app[KEY_HASS]
        if not await hass.async_add_executor_job(chemin.is_file):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.FileResponse(
            chemin,
            headers={"Content-Type": "text/csv; charset=utf-8",
                     "Content-Disposition": f'attachment; filename="{nom}"'},
        )
