# SPDX-License-Identifier: Apache-2.0
"""Mesure de la place prise par le stockage local et par l'export, sur un an simulé.

    python outils/mesurer_stockage.py [--appareils 10] [--annee 2025]

Simule une maison (réseau, solaire, batterie, et N appareils : frigo, congélateur,
pompe à chaleur, ballon, voiture, cuisson, lave-linge, lave-vaisselle,
informatique, éclairage…) pendant un an au pas de 5 minutes, de façon
déterministe (graine fixe), avec des compteurs à résolution du Wh comme la
plupart des compteurs d'énergie suivis par Home Assistant. Puis :

* écrit le stockage local exactement comme l'intégration (``stockage.py`` :
  ajouts au fil de l'eau, puis compression des mois terminés), au pas de 15 min
  et au pas de 5 min, et mesure la taille sur disque ;
* refait la même chose sans arrondi au Wh (cas défavorable : valeurs à 6 décimales
  pleines) ;
* produit l'export « SBG HA export » d'un an (``sbg_format.exporter``) au pas de
  60, 15 et 5 min, comme si l'intégration tournait depuis un an, et mesure sa
  taille non compressée.

Python 3.9+, bibliothèque standard seulement ; n'importe pas Home Assistant.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import math
from pathlib import Path
import random
import sys
import tempfile
import time

ICI = Path(__file__).resolve().parent
MODULES = ICI.parent / "custom_components" / "sbg_energy_export"


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, MODULES / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module  # nécessaire aux dataclasses
    spec.loader.exec_module(module)
    return module


stockage = _charger("stockage")
F = _charger("sbg_format")

PAS = 300
KWH = PAS / 3.6e6  # W pendant 5 min → kWh


# ------------------------------------------------------------------ simulation
def simuler(annee: int, n_appareils: int, graine: int = 2026) -> tuple[list[str], dict[str, dict[int, float]]]:
    """Énergies (kWh) par statistique et par période de 5 min, sans arrondi."""
    r = random.Random(graine)
    debut = int(datetime(annee, 1, 1, tzinfo=timezone.utc).timestamp())
    fin = int(datetime(annee + 1, 1, 1, tzinfo=timezone.utc).timestamp())
    noms = ["frigo", "congelateur", "pac", "ballon", "voiture", "cuisson", "lave_linge", "lave_vaisselle",
            "informatique", "eclairage", "seche_linge", "piscine"]
    appareils = [f"sensor.{n}" for n in (noms * 3)[:n_appareils]]
    appareils = [a if appareils.index(a) == i else f"{a}_{i}" for i, a in enumerate(appareils)]
    ids = ["sensor.import", "sensor.export", "sensor.pv", "sensor.bat_charge", "sensor.bat_decharge", *appareils]
    e: dict[str, dict[int, float]] = {s: {} for s in ids}
    soc, cap = 5.0, 10.0
    jour_courant, plan = -1, {}
    for t in range(debut, fin, PAS):
        d = datetime.fromtimestamp(t, timezone.utc)
        jour = (t - debut) // 86400
        minute = d.hour * 60 + d.minute
        saison = math.cos(2 * math.pi * (jour - 15) / 365)  # 1 en hiver, -1 en été
        if jour != jour_courant:  # tirages du jour
            jour_courant = jour
            plan = {
                "voiture": (r.randint(17 * 60, 21 * 60), r.randint(90, 240)) if r.random() < 0.45 else None,
                "ballon": r.randint(80, 150),
                "lave_linge": r.randint(9 * 60, 20 * 60) if r.random() < 0.4 else None,
                "lave_vaisselle": r.randint(19 * 60, 22 * 60) if r.random() < 0.8 else None,
                "seche_linge": r.randint(10 * 60, 20 * 60) if r.random() < 0.25 else None,
                "nuages": r.uniform(0.2, 1.0),
                "cuisson": (r.randint(11 * 60 + 30, 12 * 60 + 30), r.randint(18 * 60, 19 * 60 + 30)),
            }
        temp = 10 - 9 * saison + 4 * math.sin(2 * math.pi * (minute - 9 * 60) / 1440) + r.gauss(0, 0.5)
        w: dict[str, float] = {}
        for a in appareils:
            n = a.split(".")[1].rsplit("_", 1)[0] if a.split(".")[1][-1].isdigit() else a.split(".")[1]
            p = 0.0
            if n == "frigo":
                p = 95 if (minute % 60) < 20 else 2
            elif n == "congelateur":
                p = 85 if ((minute + 25) % 55) < 18 else 2
            elif n == "pac":
                p = max(0.0, (16 - temp) * 110) * r.uniform(0.85, 1.15) if (minute % 30) < 25 else 15
            elif n == "ballon":
                p = 2400 if 60 <= minute < 60 + plan["ballon"] else 0
            elif n == "voiture" and plan["voiture"]:
                h0, dur = plan["voiture"]
                p = 7400 if 0 <= (minute - h0) % 1440 < dur else 0
            elif n == "cuisson":
                p = sum(1800 * r.uniform(0.6, 1.0) for h0 in plan["cuisson"] if 0 <= minute - h0 < 40)
            elif n in ("lave_linge", "lave_vaisselle", "seche_linge") and plan[n] is not None:
                x = minute - plan[n]
                p = (2000 if x < 20 else 180) if 0 <= x < 110 else 0
            elif n == "informatique":
                p = 70 + r.uniform(0, 25)
            elif n == "eclairage":
                p = r.uniform(80, 250) if minute >= 17 * 60 + 30 - 60 * saison or minute < 60 else 0
            elif n == "piscine":
                p = 750 if 10 * 60 <= minute < 16 * 60 and saison < 0 else 0
            w[a] = p
        base = 120 + r.uniform(0, 60)
        conso = base + sum(w.values())
        hauteur = math.sin(math.pi * (minute - (6 * 60 + 60 * saison)) / (12 * 60 - 120 * saison))
        pv = max(0.0, 6000 * hauteur * (0.65 - 0.35 * saison) * plan["nuages"] * r.uniform(0.9, 1.0))
        solde = pv - conso
        if solde > 0:
            ch = min(solde, 3000, (cap - soc) / KWH * 0.95) if soc < cap else 0
            ch = max(0.0, ch)
            soc += ch * KWH * 0.95
            dech, imp, exp = 0.0, 0.0, solde - ch
        else:
            dech = max(0.0, min(-solde, 3000, soc / KWH)) if soc > 0.5 else 0
            soc -= dech * KWH
            ch, imp, exp = 0.0, -solde - dech, 0.0
        for s, p in (("sensor.import", imp), ("sensor.export", exp), ("sensor.pv", pv),
                     ("sensor.bat_charge", ch), ("sensor.bat_decharge", dech), *w.items()):
            e[s][t] = p * KWH
    return ids, e


def au_wh(e: dict[str, dict[int, float]]) -> dict[str, dict[int, float]]:
    """Compteurs à résolution du Wh : énergie = différence de cumuls arrondis."""
    sortie = {}
    for s, par_t in e.items():
        cumul, prec, d = 0.0, 0.0, {}
        for t in sorted(par_t):
            cumul += par_t[t]
            arrondi = round(cumul, 3)
            d[t] = round(arrondi - prec, 3)
            prec = arrondi
        sortie[s] = d
    return sortie


def par_quart(e: dict[str, dict[int, float]]) -> dict[str, dict[int, float]]:
    return {s: F.regrouper(par_t, 300, 900) for s, par_t in e.items()}


def par_heure_cumuls(e: dict[str, dict[int, float]]) -> dict[str, list[dict]]:
    """Lignes horaires « sum » comme les statistiques à long terme."""
    sortie = {}
    for s, par_t in e.items():
        heures: dict[int, float] = {}
        for t, v in par_t.items():
            heures[t - t % 3600] = heures.get(t - t % 3600, 0.0) + v
        cumul, lignes = 0.0, []
        premier = min(heures)
        lignes.append({"start": premier - 3600, "sum": 0.0})
        for t in sorted(heures):
            cumul += heures[t]
            lignes.append({"start": t, "sum": cumul})
        sortie[s] = lignes
    return sortie


# ------------------------------------------------------------------ mesures
def taille_stockage(dossier: Path, pas_min: int, valeurs: dict[str, dict[int, float]], annee: int) -> tuple[int, int]:
    """Écrit un an comme l'intégration (ajout jour par jour), compresse ; rend (octets .gz, nb fichiers)."""
    jours: dict[int, dict[str, dict[int, float]]] = {}
    for s, par_t in valeurs.items():
        for t, v in par_t.items():
            jours.setdefault(t // 86400, {}).setdefault(s, {})[t] = v
    for j in sorted(jours):
        stockage.enregistrer(dossier, pas_min, jours[j])
    stockage.entretenir(dossier, f"{annee + 1}-01", f"{annee - 2}-01")
    fichiers = [f for f in dossier.iterdir() if f.name.endswith(".csv.gz")]
    return sum(f.stat().st_size for f in fichiers), len(fichiers)


def taille_clair(dossier: Path) -> int:
    import gzip
    return sum(len(gzip.decompress(f.read_bytes())) for f in dossier.glob("*.csv.gz"))


def principal(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--appareils", type=int, default=10)
    p.add_argument("--annee", type=int, default=2025)
    a = p.parse_args(argv)
    t0 = time.time()
    ids, brut = simuler(a.annee, a.appareils)
    wh = au_wh(brut)
    print(f"Un an simulé ({a.annee}) : {len(ids)} statistiques (5 sources + {a.appareils} appareils), "
          f"{len(wh[ids[0]])} périodes de 5 min ({time.time() - t0:.0f} s).")
    mo = 1e6
    with tempfile.TemporaryDirectory() as tmp:
        racine = Path(tmp)
        print("\nStockage local (mois terminés compressés, gzip -9) :")
        for libelle, valeurs in (("compteurs au Wh", wh), ("sans arrondi (cas défavorable)", brut)):
            for pas, v in ((15, par_quart(valeurs)), (5, valeurs)):
                d = racine / f"{libelle[:3]}_{pas}"
                octets, n = taille_stockage(d, pas, v, a.annee)
                print(f"  pas de {pas:>2} min, {libelle:<32}: {octets / mo:6.2f} Mo compressé "
                      f"({taille_clair(d) / mo:6.1f} Mo en clair, {n} fichiers)")
        print("\nExport « SBG HA export » d'un an, non compressé (intégration installée depuis un an) :")
        appareils = ids[5:]
        config = F.Configuration(
            {F.PRELEVEMENT: [ids[0]], F.INJECTION: [ids[1]], F.SOLAIRE: [ids[2]], F.CHARGE: [ids[3]],
             F.DECHARGE: [ids[4]]},
            [F.Appareil(s, "autre") for s in appareils])
        horaires = par_heure_cumuls(wh)
        debut = int(datetime(a.annee, 1, 1, tzinfo=timezone.utc).timestamp())
        fin = int(datetime(a.annee + 1, 1, 1, tzinfo=timezone.utc).timestamp())
        for pas, mesures in ((60, None), (15, par_quart(wh)), (5, wh)):
            t1 = time.time()
            texte = F.exporter(config, horaires, debut, fin, pas, "Europe/Brussels", "mesure", fin, mesures)
            lignes = texte.count("\n") - sum(1 for l in texte.splitlines() if l.startswith("#")) - 1
            print(f"  pas de {pas:>2} min : {len(texte.encode()) / mo:6.1f} Mo, {lignes} lignes "
                  f"({time.time() - t1:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
