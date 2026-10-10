# SPDX-License-Identifier: Apache-2.0
"""Envoi direct vers analyse.sbg-energy.com (versions 0.3.0 et 0.4.0). DÉSACTIVÉ par défaut.

Rien ne part tant que l'utilisateur n'a pas, dans les options de l'intégration,
coché « Envoyer à analyse.sbg-energy.com » ET connecté son compte SBG Energy.

* **Connexion, une seule fois** : flux OAuth 2.0 « Device Authorization Grant »
  (RFC 8628) de Keycloak, client PUBLIC ``sbg-ha-export``. L'intégration affiche
  un lien et un code ; l'utilisateur se connecte à son compte (avec son code à
  6 chiffres) sur auth.sbg-energy.com et valide. Aucun mot de passe ni secret
  client dans Home Assistant : seul le jeton de rafraîchissement (hors ligne,
  révocable depuis le compte) est gardé dans l'entrée de configuration. Les
  jetons ne sont JAMAIS journalisés.
* **Synchronisation incrémentale** : le service dit quels jours il a déjà (par
  pas et par installation) ; l'intégration n'envoie que les jours UTC complets
  qui manquent (tout l'historique la première fois, puis la suite, trous
  compris), par morceaux, au format « SBG HA export » : exactement le contenu de
  l'export manuel (appareils choisis, sans nom d'entité, au pas choisi).
* **Au plus un envoi par mois**, imposé par le SERVICE (à partir du 2 du mois) ;
  « Envoyer maintenant » y est soumis aussi. L'intégration retient la date du
  prochain envoi permis et ne contacte pas le service avant.
* **Réimport** (service ``reimporter``) : renvoie une période choisie et
  REMPLACE ces jours côté service (3 fois par mois au plus, côté service).
* Le jeton hors ligne expire après 30 jours sans usage : il est renouvelé une
  fois par semaine (appel à auth.sbg-energy.com seulement, aucune donnée).
* **Réglages de l'installation** (0.4.0, décisions du 06/10/2026) : le code postal,
  OBLIGATOIRE pour envoyer, et la case facultative « Améliorer les outils SBG »
  partent au service quand l'utilisateur les enregistre dans les options (compte
  connecté) et juste après la connexion du compte : c'est là que le service refuse
  une 4e installation pour le même compte (le jeton est alors oublié et révoqué).
* **Pas de 5 min** : le service et l'intégration ne gardent le pas de 5 min que
  12 mois ; les jours plus anciens partent au quart d'heure, dans la même session.
* **Logement et gestionnaire de réseau** (0.6.0, ADR-040 étape 7) : les réglages peuvent
  porter le gestionnaire de réseau (facultatif, jamais « je ne sais pas ») et le logement
  choisi. Le service range l'installation dans un logement du compte ; s'il le dit dans sa
  réponse (champs facultatifs ``logement`` et ``logements``), l'intégration l'affiche et
  laisse choisir. Sans ces champs (service plus ancien), rien ne change : le service range
  par code postal, comme pour 0.5.
* **Installation effacée** (0.6.0) : si le titulaire a fait effacer les données de cette
  installation depuis son compte, le service refuse tout (``installation_effacee``).
  L'intégration coupe alors l'envoi, le dit (notification persistante, et dans les options)
  et ne réessaie plus : sans cela, la tâche quotidienne redemanderait chaque jour.
* **Installation déconnectée** (0.6.0, décision du 09/10/2026) : « arrêtée » depuis le compte,
  elle est refusée (403 ``installation_deconnectee``) mais peut être reprise d'un clic dans le
  compte. L'intégration continue donc d'essayer chaque jour, mais ne le dit qu'UNE fois
  (notification persistante dédiée), au lieu d'un « Rien n'a été envoyé » chaque matin. La
  notification part dès que le service accepte de nouveau l'installation, ou que l'envoi est
  désactivé.
* **Texte accepté** (0.6.0) : chaque requête de réglages nomme le texte de l'étape Envoi
  réellement affiché (``texte_consentement``, voir ``const.TEXTE_CONSENTEMENT``), pour la
  preuve gardée par le service.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    API_URL,
    AUTH_URL,
    CLIENT_ID,
    DATA_JETON,
    DATA_SOURCE,
    DOMAIN,
    GRDS,
    JOURS_PAR_MORCEAU,
    OCTETS_MAX,
    OPT_AMELIORER,
    OPT_CODE_POSTAL,
    OPT_ENVOI,
    OPT_GRD,
    OPT_PAS_ENVOI,
    PAS_ENVOI_DEFAUT,
    PORTEES,
    RENOUVELER_JETON_J,
    TEXTE_CONSENTEMENT,
    VERSION,
)
from .export import async_premier_jour, async_texte

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)
DELAI_S = 60
GRANT_DEVICE = "urn:ietf:params:oauth:grant-type:device_code"
URL_JETON = f"{AUTH_URL}/protocol/openid-connect/token"
URL_APPAREIL = f"{AUTH_URL}/protocol/openid-connect/auth/device"
URL_REVOCATION = f"{AUTH_URL}/protocol/openid-connect/revoke"
AGENT = f"sbg-energy-export/{VERSION} (Home Assistant)"
EFFACEE = "installation_effacee"   # code d'erreur du service : données de l'installation effacées
NOTIF_EFFACEE = f"{DOMAIN}_installation_effacee"
DECONNECTEE = "installation_deconnectee"   # 403 du service : installation « arrêtée » depuis le compte
NOTIF_DECONNECTEE = f"{DOMAIN}_installation_deconnectee"


class EnvoiErreur(HomeAssistantError):
    """Erreur montrée telle quelle à l'utilisateur (jamais de jeton dedans)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def nouvelle_source() -> str:
    """Identifiant ALÉATOIRE de l'installation, sans lien avec elle (32 caractères hexadécimaux)."""
    return secrets.token_hex(16)


def actif(entree: ConfigEntry) -> bool:
    """Envoi activé ET compte connecté : sinon, aucun appel réseau."""
    return bool(entree.options.get(OPT_ENVOI) and entree.data.get(DATA_JETON))


# ------------------------------------------------------------------ connexion
@dataclass
class Connexion:
    """Réponse de l'autorisation d'appareil (RFC 8628)."""

    device_code: str
    code: str
    url: str
    url_complete: str
    intervalle: float
    expire: float


async def _poster(hass: HomeAssistant, url: str, donnees: dict[str, str]) -> tuple[int, dict[str, Any]]:
    session = async_get_clientsession(hass)
    try:
        async with session.post(url, data=donnees, headers={"User-Agent": AGENT},
                                timeout=aiohttp.ClientTimeout(total=DELAI_S)) as r:
            try:
                corps = await r.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                corps = {}
            return r.status, corps if isinstance(corps, dict) else {}
    except (aiohttp.ClientError, TimeoutError) as e:
        raise EnvoiErreur("reseau", "auth.sbg-energy.com injoignable : réessayez plus tard.") from e


async def async_demarrer_connexion(hass: HomeAssistant) -> Connexion:
    """Demande un code d'appareil à Keycloak."""
    statut, r = await _poster(hass, URL_APPAREIL, {"client_id": CLIENT_ID, "scope": PORTEES})
    if statut != 200 or not r.get("device_code") or not r.get("user_code"):
        raise EnvoiErreur("connexion", "La connexion au compte SBG Energy n'a pas pu démarrer.")
    return Connexion(r["device_code"], r["user_code"], r.get("verification_uri", ""),
                     r.get("verification_uri_complete") or r.get("verification_uri", ""),
                     float(r.get("interval", 5)), time.monotonic() + float(r.get("expires_in", 600)))


async def async_attendre_connexion(hass: HomeAssistant, c: Connexion) -> str:
    """Attend que l'utilisateur valide le code ; rend le jeton de rafraîchissement."""
    intervalle = c.intervalle
    while time.monotonic() < c.expire:
        await asyncio.sleep(intervalle)
        statut, r = await _poster(hass, URL_JETON, {"grant_type": GRANT_DEVICE, "device_code": c.device_code,
                                                    "client_id": CLIENT_ID})
        if statut == 200 and r.get("refresh_token"):
            if "ha-export" not in str(r.get("scope", "")).split():
                raise EnvoiErreur("portee", "Le compte n'a pas accordé l'envoi des exports.")
            return str(r["refresh_token"])
        erreur = r.get("error")
        if erreur == "authorization_pending":
            continue
        if erreur == "slow_down":
            intervalle += 5
            continue
        if erreur == "access_denied":
            raise EnvoiErreur("refuse", "Connexion refusée sur auth.sbg-energy.com.")
        if erreur == "expired_token":
            break
        raise EnvoiErreur("connexion", "La connexion au compte SBG Energy a échoué.")
    raise EnvoiErreur("expire", "Le code a expiré : recommencez la connexion.")


async def async_revoquer(hass: HomeAssistant, jeton: str) -> None:
    """Retire l'autorisation chez Keycloak (au mieux : l'oubli local suffit à ne plus rien envoyer)."""
    try:
        await _poster(hass, URL_REVOCATION, {"token": jeton, "token_type_hint": "refresh_token",
                                             "client_id": CLIENT_ID})
    except EnvoiErreur:
        _LOGGER.info("Révocation du jeton chez Keycloak impossible (réseau) ; il est oublié localement")


# ------------------------------------------------------------------ état local
class Etat:
    """Dernier envoi, prochain envoi permis (donné par le service), dernier renouvellement du jeton.
    Aucun secret ici (``.storage/sbg_energy_export.envoi``).

    Le fichier porte l'identifiant de l'installation (``source``) dont il parle : celui d'une
    autre installation (intégration supprimée puis ajoutée de nouveau) n'est pas repris."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.envoi")
        self.donnees: dict[str, Any] = {}
        self._ecouteurs: list[Callable[[], None]] = []

    async def async_charger(self, source: str | None = None) -> None:
        """Charge l'état de l'installation ``source``.

        Un état noté pour une AUTRE installation est écarté : « effacée », logement, date du
        prochain envoi… ne valent que pour elle. Un état sans ``source`` (écrit avant 0.6.0) est
        celui de l'installation en place : il est gardé et prend son identifiant."""
        donnees = await self._store.async_load() or {}
        if source and donnees.get("source") not in (None, source):
            donnees = {}
        if source:
            donnees["source"] = source
        self.donnees = donnees

    async def async_oublier_compte(self) -> None:
        """Tout ce qui vient du compte (réglages vus chez le service, logement, installation
        effacée ou déconnectée, dernier et prochain envoi) : seul l'identifiant de l'installation
        reste. Un autre compte, connecté ensuite, ne doit rien en reprendre."""
        self.donnees = {"source": self.donnees["source"]} if self.donnees.get("source") else {}
        await self._store.async_save(self.donnees)
        for ecouteur in list(self._ecouteurs):
            ecouteur()

    async def async_supprimer(self) -> None:
        """Intégration supprimée : l'état de son installation ne sert plus à rien."""
        self.donnees = {}
        await self._store.async_remove()

    async def async_noter(self, **valeurs: Any) -> None:
        self.donnees.update(valeurs)
        await self._store.async_save(self.donnees)
        for ecouteur in list(self._ecouteurs):
            ecouteur()

    def async_ecouter(self, ecouteur: Callable[[], None]) -> Callable[[], None]:
        """Prévenu à chaque changement (capteur « Dernier envoi »)."""
        self._ecouteurs.append(ecouteur)
        return lambda: self._ecouteurs.remove(ecouteur)

    @property
    def effacee(self) -> bool:
        """Le service a répondu ``installation_effacee`` : l'envoi a été coupé ici."""
        return bool(self.donnees.get("effacee"))

    @property
    def deconnectee(self) -> bool:
        """Le service a répondu ``installation_deconnectee`` et la notification a été faite."""
        return bool(self.donnees.get("deconnectee"))

    @property
    def logement(self) -> dict[str, str] | None:
        """Logement où l'installation envoie, si le service l'a dit (0.6.0)."""
        lg = self.donnees.get("logement")
        return lg if isinstance(lg, dict) and lg.get("id") else None

    @property
    def logements(self) -> list[dict[str, str]]:
        """Logements du compte proposés par le service (vide si le service ne les donne pas)."""
        return [lg for lg in self.donnees.get("logements") or [] if isinstance(lg, dict) and lg.get("id")]

    @property
    def prochaine(self) -> date | None:
        p = self.donnees.get("prochaine")
        return date.fromisoformat(p) if p else None


# ------------------------------------------------------------------ client
class Client:
    """Appels au service avec un jeton d'accès frais (jamais journalisé)."""

    def __init__(self, hass: HomeAssistant, entree: ConfigEntry, etat: Etat) -> None:
        self.hass, self.entree, self.etat = hass, entree, etat
        self._acces: str | None = None

    async def async_acces(self) -> str:
        jeton = self.entree.data.get(DATA_JETON)
        if not jeton:
            raise EnvoiErreur("non_connecte", "Compte SBG Energy non connecté (options de l'intégration).")
        statut, r = await _poster(self.hass, URL_JETON, {"grant_type": "refresh_token", "refresh_token": jeton,
                                                         "client_id": CLIENT_ID})
        if statut == 200 and r.get("access_token"):
            nouveau = r.get("refresh_token")
            if nouveau and nouveau != jeton:
                self.hass.config_entries.async_update_entry(self.entree, data={**self.entree.data, DATA_JETON: nouveau})
            await self.etat.async_noter(renouvele=time.time())
            self._acces = str(r["access_token"])
            return self._acces
        if statut in (400, 401) and r.get("error") in ("invalid_grant", "unauthorized_client", "invalid_client"):
            # session hors ligne expirée ou autorisation retirée depuis le compte : il faut se reconnecter
            self.hass.config_entries.async_update_entry(
                self.entree, data={k: v for k, v in self.entree.data.items() if k != DATA_JETON})
            raise EnvoiErreur("reconnexion", "La connexion au compte SBG Energy a expiré ou a été retirée : "
                                             "reconnectez-la dans les options de l'intégration.")
        raise EnvoiErreur("auth", "auth.sbg-energy.com ne répond pas correctement : réessayez plus tard.")

    async def async_requete(self, methode: str, chemin: str, *, json: Any = None, params: dict[str, str] | None = None,
                            corps: bytes | None = None, entetes: dict[str, str] | None = None) -> dict[str, Any]:
        acces = self._acces or await self.async_acces()
        h = {"Authorization": f"Bearer {acces}", "User-Agent": AGENT, "Accept": "application/json", **(entetes or {})}
        if corps is not None:
            h["Content-Type"] = "text/csv; charset=utf-8"
        session = async_get_clientsession(self.hass)
        try:
            async with session.request(methode, f"{API_URL}/{chemin}", json=json, params=params, data=corps,
                                       headers=h, timeout=aiohttp.ClientTimeout(total=DELAI_S * 2)) as r:
                try:
                    reponse = await r.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    reponse = {}
                if not isinstance(reponse, dict):
                    reponse = {}
                if r.status >= 400:
                    if r.status == 401 and reponse.get("code") == "revoque":
                        self.hass.config_entries.async_update_entry(
                            self.entree, data={k: v for k, v in self.entree.data.items() if k != DATA_JETON})
                    raise EnvoiErreur(str(reponse.get("code") or r.status),
                                      str(reponse.get("message") or f"Le service a répondu {r.status}."))
                return reponse
        except (aiohttp.ClientError, TimeoutError) as e:
            raise EnvoiErreur("reseau", "analyse.sbg-energy.com injoignable : réessayez plus tard.") from e


# ------------------------------------------------------------------ jours
def _jours_couverts(plages: list[list[str]]) -> set[date]:
    out: set[date] = set()
    for a, b in plages:
        j, fin = date.fromisoformat(a), date.fromisoformat(b)
        while j <= fin:
            out.add(j)
            j += timedelta(days=1)
    return out


def morceaux(jours: list[date], taille: int) -> list[tuple[date, date]]:
    """Jours triés → [(début, fin exclue)] : suites contiguës, coupées à ``taille`` jours."""
    out: list[tuple[date, date]] = []
    for j in sorted(jours):
        if out and out[-1][1] == j and (out[-1][1] - out[-1][0]).days < taille:
            out[-1] = (out[-1][0], j + timedelta(days=1))
        else:
            out.append((j, j + timedelta(days=1)))
    return out


def fin_envoyable(maintenant: datetime | None = None) -> date:
    """Premier jour UTC NON envoyable : aujourd'hui (pas fini), et hier aussi avant 1 h UTC
    (ses dernières statistiques ne sont pas encore compilées)."""
    m = maintenant or datetime.now(UTC)
    return m.date() - timedelta(days=0 if m.hour >= 1 else 1)


@dataclass
class Bilan:
    """Résultat d'un envoi."""

    jours: int = 0
    ignores: int = 0
    refuses: int = 0
    prochaine: str | None = None
    rapport: str | None = None
    compte: str | None = None


def _un_logement(v: Any) -> dict[str, str] | None:
    """``{"id", "nom"}`` du service, en texte ; None si la forme n'est pas celle attendue."""
    if not isinstance(v, dict) or v.get("id") in (None, "") or isinstance(v.get("id"), bool):
        return None
    return {"id": str(v["id"])[:64], "nom": str(v.get("nom") or v["id"])[:100]}


def logements_de(reponse: dict[str, Any]) -> dict[str, Any]:
    """Champs facultatifs ``logement`` et ``logements`` d'une réponse du service (0.6.0).

    Rend seulement ce que le service a donné : un service qui ne les connaît pas encore ne
    change rien à ce qui est gardé (comportement de 0.5)."""
    out: dict[str, Any] = {}
    if "logement" in reponse:
        out["logement"] = _un_logement(reponse["logement"])
    if isinstance(reponse.get("logements"), list):
        out["logements"] = [lg for lg in map(_un_logement, reponse["logements"]) if lg]
    return out


async def async_reglages(hass: HomeAssistant, entree: ConfigEntry, code_postal: str, accord: bool,
                         grd: str = "", logement: str | None = None) -> dict[str, Any]:
    """Code postal, accord « Améliorer les outils SBG », gestionnaire de réseau (facultatif) et
    logement (seulement s'il a été choisi dans la liste donnée par le service), au service.
    Lève EnvoiErreur (message du service tel quel : 4e installation, code postal inconnu…).

    ``grd`` vide ou « je ne sais pas » n'est pas envoyé : le service garde le gestionnaire qu'il
    connaît (donné sur la page du logement) ou le déduit du code postal quand il est certain ;
    une déduction faite ici passerait, chez le service, pour une déclaration du client."""
    etat: Etat = entree.runtime_data.etat
    corps: dict[str, Any] = {"source": entree.data.get(DATA_SOURCE), "code_postal": code_postal,
                             "accord_amelioration": bool(accord), "texte_consentement": TEXTE_CONSENTEMENT}
    if grd in GRDS:
        corps[OPT_GRD] = grd
    if logement:
        corps["logement"] = logement
    try:
        r = await Client(hass, entree, etat).async_requete("POST", "reglages", json=corps)
    except EnvoiErreur as e:
        if e.code == EFFACEE:
            await async_couper_effacee(hass, entree, e)
        raise
    await etat.async_noter(reglages=r.get("reglages"), effacee=False, **logements_de(r))
    persistent_notification.async_dismiss(hass, NOTIF_EFFACEE)
    await async_oublier_deconnectee(hass, entree)
    return r


async def async_signaler_deconnectee(hass: HomeAssistant, entree: ConfigEntry, e: EnvoiErreur) -> None:
    """Installation « arrêtée » depuis le compte : le dire UNE fois, sans couper l'envoi.

    Contrairement à ``installation_effacee``, rien n'est perdu côté service et le titulaire peut la
    reprendre d'un clic : la tâche quotidienne continue donc d'essayer (un appel ``jours`` par jour,
    sans données). Seule la notification est unique : elle n'est refaite qu'après avoir été retirée
    par le retour à la normale (``async_oublier_deconnectee``)."""
    etat: Etat = entree.runtime_data.etat
    if etat.deconnectee:
        _LOGGER.debug("Envoi SBG Energy : installation toujours déconnectée depuis le compte")
        return
    _LOGGER.warning("Envoi SBG Energy refusé : %s", e.message)
    await etat.async_noter(deconnectee=True)
    persistent_notification.async_create(
        hass,
        f"{e.message}\n\nHome Assistant réessaiera chaque jour, sans données, et ne vous le redira pas : "
        "l'envoi reprendra seul dès que vous aurez repris cette installation depuis votre compte SBG Energy. "
        "Pour ne plus essayer, décochez « Envoyer à analyse.sbg-energy.com » dans les options de "
        "l'intégration. Les mesures gardées dans Home Assistant ne sont pas touchées.",
        title="SBG Energy Export : installation déconnectée", notification_id=NOTIF_DECONNECTEE)


async def async_oublier_deconnectee(hass: HomeAssistant, entree: ConfigEntry) -> None:
    """Le service accepte de nouveau l'installation, ou l'envoi est désactivé : la notification
    « déconnectée » n'a plus lieu d'être (et pourra être refaite si le refus revient)."""
    etat: Etat = entree.runtime_data.etat
    if etat.deconnectee:
        await etat.async_noter(deconnectee=False)
    persistent_notification.async_dismiss(hass, NOTIF_DECONNECTEE)


async def async_oublier_compte(hass: HomeAssistant, etat: Etat) -> None:
    """Compte déconnecté, autre compte connecté, ou intégration supprimée : l'état gardé et les
    notifications « envoi coupé » et « installation déconnectée » parlaient du compte précédent.

    ``logements_de`` garde exprès ce qui est connu quand le service ne redonne pas ses champs
    facultatifs : sans cet oubli, le logement d'un compte s'afficherait pour le suivant."""
    await etat.async_oublier_compte()
    persistent_notification.async_dismiss(hass, NOTIF_EFFACEE)
    persistent_notification.async_dismiss(hass, NOTIF_DECONNECTEE)


async def async_couper_effacee(hass: HomeAssistant, entree: ConfigEntry, e: EnvoiErreur) -> None:
    """Installation effacée depuis le compte : l'envoi est coupé ici, une notification le dit, et
    plus aucun essai ne part (la tâche quotidienne ne fait rien tant que l'envoi est décoché).

    Les options changent sans recharger l'entrée (le collecteur continue) : ``actif()`` relit les
    options à chaque fois."""
    etat: Etat = entree.runtime_data.etat
    if not etat.effacee:
        _LOGGER.warning("Envoi SBG Energy coupé : %s", e.message)
    await etat.async_noter(effacee=True, logement=None, logements=[])
    # L'entrée n'est pas rechargée (voir plus bas) : la notification « déconnectée », qui promet
    # un nouvel essai chaque jour, doit être retirée ici, puisque plus rien ne réessaiera.
    await async_oublier_deconnectee(hass, entree)
    persistent_notification.async_create(
        hass,
        f"{e.message}\n\n**L'envoi automatique est coupé dans Home Assistant** : il ne réessaiera plus. "
        "Pour le reprendre : autorisez d'abord cette installation à nouveau depuis votre compte SBG Energy, "
        "puis cochez de nouveau « Envoyer à analyse.sbg-energy.com » dans les options de l'intégration "
        "(Configurer, étape Envoi). Les mesures gardées dans Home Assistant ne sont pas touchées.",
        title="SBG Energy Export : envoi coupé", notification_id=NOTIF_EFFACEE)
    if entree.options.get(OPT_ENVOI):
        options = {**entree.options, OPT_ENVOI: False}
        # AVANT la mise à jour : l'écouteur des options (tâche immédiate) compare à celles-ci et ne
        # recharge donc pas l'entrée
        entree.runtime_data.options = dict(options)
        hass.config_entries.async_update_entry(entree, options=options)


async def _envoyer_jours(hass: HomeAssistant, entree: ConfigEntry, client: Client, sid: str, mode: str, pas: int,
                         jours: list[date], limites: dict[str, int], bilan: Bilan) -> None:
    """Envoie ``jours`` au pas ``pas`` (celui de la session, ou 15 pour les vieux jours d'une
    session à 5 min)."""
    if not jours:
        return
    collecteur = entree.runtime_data.collecteur
    if pas != 60:
        await collecteur.async_rattraper()
    taille = min(JOURS_PAR_MORCEAU[pas], int(limites.get("jours_max", 92)))
    octets_max = min(OCTETS_MAX, int(limites.get("octets_max", OCTETS_MAX)))
    a_faire = morceaux(jours, taille)
    while a_faire:
        debut, fin = a_faire.pop(0)
        texte, _ = await async_texte(hass, dict(entree.options), collecteur, pas, debut, fin, rattraper=False)
        corps = texte.encode("utf-8")
        if len(corps) > octets_max and (fin - debut).days > 1:
            milieu = debut + timedelta(days=(fin - debut).days // 2)
            a_faire[:0] = [(debut, milieu), (milieu, fin)]
            continue
        r = await client.async_requete("POST", "import", corps=corps,
                                       entetes={"X-SBG-Synchro": sid, "X-SBG-Mode": mode})
        bilan.jours += len(r.get("ajoutes", [])) + len(r.get("remplaces", []))
        bilan.ignores += len(r.get("ignores", []))
        bilan.refuses += len(r.get("refuses", []))


async def _session(hass: HomeAssistant, entree: ConfigEntry, mode: str, periode: tuple[date, date] | None,
                   manuel: bool) -> Bilan | None:
    """Une session d'envoi. ``installation_effacee`` coupe l'envoi quelle que soit la requête qui
    le reçoit (jours, réglages, ouverture, morceau), puis l'erreur remonte comme les autres.

    Aujourd'hui le service ne répond ainsi qu'aux requêtes qui créeraient l'installation (réglages
    et ouverture de session) ; le traiter ici, une fois, évite de dépendre de ce détail : sinon un
    refus venu d'une autre requête laisserait l'envoi coché et la tâche réessaierait chaque jour."""
    try:
        return await _session_ouverte(hass, entree, mode, periode, manuel)
    except EnvoiErreur as e:
        if e.code == EFFACEE and actif(entree):   # pas déjà coupé (par async_reglages)
            await async_couper_effacee(hass, entree, e)
        raise


async def _session_ouverte(hass: HomeAssistant, entree: ConfigEntry, mode: str, periode: tuple[date, date] | None,
                           manuel: bool) -> Bilan | None:
    d = entree.runtime_data
    etat: Etat = d.etat
    if not actif(entree):
        if manuel:
            raise EnvoiErreur("desactive", "L'envoi vers analyse.sbg-energy.com est désactivé (options de "
                                           "l'intégration) : rien n'a été envoyé.")
        return None
    source = entree.data.get(DATA_SOURCE)
    pas = int(entree.options.get(OPT_PAS_ENVOI, PAS_ENVOI_DEFAUT))
    client = Client(hass, entree, etat)
    j = await client.async_requete("GET", "jours", params={"source": source, "pas": str(pas)})
    # le service répond de nouveau : l'installation n'est plus (ou n'a jamais été) déconnectée
    await async_oublier_deconnectee(hass, entree)
    serveur = j.get("reglages") or {}
    await etat.async_noter(reglages=serveur, **logements_de(j))
    cp = str(entree.options.get(OPT_CODE_POSTAL) or "")
    if cp and not serveur.get("code_postal"):
        # réglages pas encore arrivés au service (réseau coupé à la connexion, ou installation
        # effacée depuis le compte : le service le dit ici) : on les redonne
        await async_reglages(hass, entree, cp, bool(entree.options.get(OPT_AMELIORER)),
                             str(entree.options.get(OPT_GRD) or ""))
    synchro = j.get("synchro") or {}
    if mode == "complement" and not synchro.get("permise"):
        await etat.async_noter(prochaine=synchro.get("prochaine"))
        if manuel:
            raise EnvoiErreur("limite_mensuelle", "Un envoi par mois au plus : prochain envoi possible le "
                              f"{_date_fr(synchro.get('prochaine'))}.")
        return None
    ouverture: dict[str, Any] = {"source": source, "pas": pas, "mode": mode}
    if periode:
        ouverture.update(debut=periode[0].isoformat(), fin=periode[1].isoformat())
    s = await client.async_requete("POST", "synchros", json=ouverture)
    jour_min = date.fromisoformat(j.get("jour_min") or s.get("jour_min") or "2000-01-01")
    fin = fin_envoyable()
    if periode:
        debut, fin = max(periode[0], jour_min), min(periode[1], fin)
        jours = [debut + timedelta(days=k) for k in range(max(0, (fin - debut).days))]
    else:
        premier = max(await async_premier_jour(hass, dict(entree.options)), jour_min)
        deja = _jours_couverts((j.get("couverture") or {}).get(str(pas), []))
        jours = [premier + timedelta(days=k) for k in range(max(0, (fin - premier).days))
                 if premier + timedelta(days=k) not in deja]
    bilan = Bilan()
    # Pas de 5 min gardé 12 mois (service et intégration) : les jours plus anciens partent au
    # quart d'heure, dans la même session (le service l'accepte pour une session à 5 min).
    limite_5 = date.fromisoformat(j["jour_min_5min"]) if pas == 5 and j.get("jour_min_5min") else None
    vieux = [d for d in jours if limite_5 and d < limite_5]
    recents = [d for d in jours if not (limite_5 and d < limite_5)]
    try:
        await _envoyer_jours(hass, entree, client, s["id"], mode, 15, vieux, j.get("morceau") or {}, bilan)
        await _envoyer_jours(hass, entree, client, s["id"], mode, pas, recents, j.get("morceau") or {}, bilan)
    finally:
        # même interrompu, la session est fermée : les jours arrivés comptent et le rapport se recalcule
        try:
            t = await client.async_requete("POST", f"synchros/{s['id']}/terminer")
        except EnvoiErreur as e:
            t = {}
            if e.code == EFFACEE and actif(entree):   # cette erreur-ci ne remonte pas : coupé ici
                await async_couper_effacee(hass, entree, e)
    bilan.prochaine = (t.get("synchro") or {}).get("prochaine")
    bilan.rapport, bilan.compte = t.get("rapport"), t.get("compte")
    await etat.async_noter(derniere=datetime.now(UTC).isoformat(timespec="seconds"), prochaine=bilan.prochaine,
                           jours=bilan.jours, mode=mode)
    return bilan


def _date_fr(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else "?"


def _notifier(hass: HomeAssistant, texte: str) -> None:
    persistent_notification.async_create(hass, texte, title="SBG Energy Export : envoi",
                                         notification_id=f"{DOMAIN}_envoi")


def _texte_bilan(b: Bilan, mode: str) -> str:
    quoi = "remplacé(s)" if mode == "remplacement" else "envoyé(s)"
    lignes = [f"**{b.jours} jour(s) {quoi}** à analyse.sbg-energy.com."]
    if b.ignores:
        lignes.append(f"{b.ignores} jour(s) déjà présents n'ont pas été renvoyés.")
    if b.refuses:
        lignes.append(f"{b.refuses} jour(s) refusés par le service (incomplets ou trop anciens).")
    if b.rapport == "reglages_manquants":
        lignes.append("Pour obtenir votre rapport, donnez votre code postal dans les options de l'intégration "
                      f"ou dans votre compte : {b.compte or 'analyse.sbg-energy.com/home-assistant/'}")
    elif b.rapport == "calcul":
        lignes.append("Votre rapport se met à jour dans votre compte.")
    if b.prochaine:
        lignes.append(f"Prochain envoi possible le {_date_fr(b.prochaine)}.")
    return "\n\n".join(lignes)


async def async_synchroniser(hass: HomeAssistant, entree: ConfigEntry, manuel: bool = False) -> Bilan | None:
    """Envoie les jours manquants. ``manuel`` : bouton ou service (erreur montrée à l'utilisateur)."""
    try:
        bilan = await _session(hass, entree, "complement", None, manuel)
    except EnvoiErreur as e:
        if e.code == DECONNECTEE:                 # dit une seule fois, par sa propre notification
            await async_signaler_deconnectee(hass, entree, e)
        elif e.code != EFFACEE:                   # déjà dit par sa propre notification
            _LOGGER.warning("Envoi SBG Energy non fait : %s", e.message)
            _notifier(hass, f"Rien n'a été envoyé : {e.message}")
        raise
    if bilan is not None:
        _LOGGER.info("Envoi SBG Energy : %d jour(s) envoyé(s)", bilan.jours)
        _notifier(hass, _texte_bilan(bilan, "complement"))
    return bilan


async def async_reimporter(hass: HomeAssistant, entree: ConfigEntry, debut: date, fin: date) -> Bilan:
    """Renvoie [debut, fin[ et REMPLACE ces jours côté service."""
    if fin <= debut:
        raise EnvoiErreur("periode", "La fin doit suivre le début.")
    try:
        bilan = await _session(hass, entree, "remplacement", (debut, fin), True)
    except EnvoiErreur as e:
        if e.code == DECONNECTEE:
            await async_signaler_deconnectee(hass, entree, e)
        elif e.code != EFFACEE:
            _LOGGER.warning("Réimport SBG Energy non fait : %s", e.message)
            _notifier(hass, f"Réimport non fait : {e.message}")
        raise
    assert bilan is not None
    _notifier(hass, _texte_bilan(bilan, "remplacement"))
    return bilan


async def async_tache_quotidienne(hass: HomeAssistant, entree: ConfigEntry) -> None:
    """Chaque jour, à une heure propre à l'installation : rien si l'envoi est désactivé ; sinon
    l'envoi du mois quand le service le permet, ou au moins le renouvellement hebdomadaire du jeton."""
    if not actif(entree):
        return
    etat: Etat = entree.runtime_data.etat
    p = etat.prochaine
    try:
        if p is None or datetime.now(UTC).date() >= p:
            await async_synchroniser(hass, entree)
        elif time.time() - float(etat.donnees.get("renouvele", 0)) > RENOUVELER_JETON_J * 86400:
            await Client(hass, entree, etat).async_acces()
    except EnvoiErreur:
        pass  # déjà noté et notifié ; on réessaie demain


def heure_quotidienne(source: str | None) -> tuple[int, int]:
    """Heure locale de la tâche, entre 3 h et 5 h 59, tirée de l'identifiant aléatoire (étale la charge)."""
    n = int((source or "0" * 8)[:8], 16)
    return 3 + n % 3, (n // 3) % 60
