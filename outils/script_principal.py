# SPDX-License-Identifier: Apache-2.0

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
import zipfile

VERSION_SCRIPT = "0.3.0"
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
                   help="avec --depuis-json ou --depuis-csv : sensor.x=voiture "
                        "(pac, ballon, cuisson, lavage, froid, informatique, eclairage, ventilation, pompe, autre)")
    p.add_argument("--appareils", help="avec --url : tous, aucun, ou numéros 1,3")
    p.add_argument("--categorie", action="append", default=[], help="avec --url : 1=voiture")
    p.add_argument("--pas", type=int, choices=(5, 15, 60), default=60,
                   help="60 (défaut) ; 15 ou 5 : les ~10 derniers jours au pas fin, le reste en lignes "
                        "horaires (version 2 du format)")
    p.add_argument("--debut", help="AAAA-MM-JJ (UTC), par défaut le début des statistiques")
    p.add_argument("--fin", help="AAAA-MM-JJ (UTC, exclu), par défaut l'heure en cours")
    p.add_argument("--fuseau", default=None,
                   help="fuseau de la maison (par défaut celui de Home Assistant, sinon Europe/Brussels)")
    p.add_argument("--sortie", default="sbg_ha_export.csv",
                   help="fichier écrit ; s'il se termine par .zip : le CSV compressé dans une archive ZIP")
    a = p.parse_args(argv)

    maintenant = int(time.time())
    fin = en_secondes(a.fin + "T00:00:00Z") if a.fin else maintenant - maintenant % 3600
    debut = en_secondes(a.debut + "T00:00:00Z") if a.debut else None
    fuseau = a.fuseau or "Europe/Brussels"
    mesures = None
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
            if a.pas != 60:
                cinq = statistiques(ws, ids, max(debut, fin - 12 * 86400) - 300, fin, "5minute", 86400)
                mesures = variations_par_quart(cinq) if a.pas == 15 else variations_par_cinq(cinq)
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

    texte = exporter(config, horaires, debut, fin, a.pas, fuseau, generateur, maintenant, mesures, compact=True)
    if a.sortie.lower().endswith(".zip"):
        interne = os.path.basename(a.sortie)[:-4] + ".csv"
        with zipfile.ZipFile(a.sortie, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr(interne, texte.encode("utf-8"))
    else:
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
