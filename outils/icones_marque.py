# SPDX-License-Identifier: Apache-2.0
"""Images de marque de l'intégration à partir du logo officiel SBG Energy (SVG du site
sbg-energy.com, fichier ``sbg-logo.svg``, recopié ci-dessous).

    python outils/icones_marque.py

Produit, en PNG à fond transparent, recadrés au plus près (marge de 2 %) :

* ``custom_components/sbg_energy_export/brand/`` : images locales de l'intégration, prises
  en charge par Home Assistant depuis la version 2026.3 (``icon.png`` 256×256,
  ``icon@2x.png`` 512×512, ``logo.png`` / ``logo@2x.png`` (le logo SBG est le symbole
  seul : pas de texte), et les variantes ``dark_*`` pour le thème sombre (symbole clair :
  le noir officiel disparaîtrait sur fond sombre) ;
* ``docs/brands/custom_integrations/sbg_energy_export/`` : les mêmes images, prêtes pour
  une demande au dépôt ``home-assistant/brands`` (pas encore soumise),
  utile tant que HACS n'affiche pas les images locales ;
* ``docs/icone/icon.svg``, ``icon.png``, ``icon@2x.png`` : les mêmes, pour le README.

Le tracé est rendu ici, sans bibliothèque SVG (aucune n'est installée de façon fiable
sous Windows) : le logo n'a qu'un cercle et un arc en courbes de Bézier cubiques
relatives, répété trois fois par rotation. Rendu à 4096 px puis réduit (Lanczos) : net
en petit. Pillow seul.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

from PIL import Image, ImageDraw

RACINE = Path(__file__).resolve().parent.parent
NOIR = (11, 11, 12, 255)          # #0b0b0c, couleur du logo officiel
CLAIR = (242, 242, 242, 255)      # variante pour thème sombre
VIEWBOX = (156.34207, 152.12625)
TRANSLATE = (-34.522733, -59.44796)
CERCLE = (105.0, 147.5, 21.5)
ARC = ("m 119.92294,188.78424 c 22.79265,-3.79186 41.63338,-8.33975 67.96233,-34.70034 2.65219,-2.65537 "
       "3.60653,-1.92561 2.19477,2.40409 -10.67432,32.73681 -51.54502,53.77361 -79.25214,53.6918 "
       "-27.707117,-0.0818 -52.337605,-16.73787 -59.946052,-28.58733 -1.650343,-2.57026 1.631155,-3.69377 "
       "2.876712,-3.0565 28.167994,14.41163 56.29855,11.88959 66.16438,10.24828 z")
ROTATIONS = [None, (127.96517, 105.10224, 147.36657), (-118.50325, 104.48268, 142.44649)]
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 156.34207 152.12625"><g '
       'transform="translate(-34.522733,-59.44796)" fill="#0b0b0c"><circle cy="147.5" cx="105" r="21.5"/>'
       f'<path id="sbg-arc" stroke="#0b0b0c" stroke-width="0.264583" d="{ARC}"/><use href="#sbg-arc" '
       'transform="rotate(127.96517,105.10224,147.36657)"/><use href="#sbg-arc" '
       'transform="rotate(-118.50325,104.48268,142.44649)"/></g></svg>\n')


def _points_arc() -> list[tuple[float, float]]:
    """Le tracé relatif (m, c, z) en points absolus (64 pas par courbe)."""
    nombres = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", ARC)]
    x, y = nombres[0], nombres[1]
    pts = [(x, y)]
    reste = nombres[2:]
    for k in range(0, len(reste), 6):
        c1 = (x + reste[k], y + reste[k + 1])
        c2 = (x + reste[k + 2], y + reste[k + 3])
        p = (x + reste[k + 4], y + reste[k + 5])
        for i in range(1, 65):
            t = i / 64
            u = 1 - t
            pts.append((u ** 3 * x + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p[0],
                        u ** 3 * y + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p[1]))
        x, y = p
    return pts


def _tourner(p, r):
    if r is None:
        return p
    a, cx, cy = math.radians(r[0]), r[1], r[2]
    dx, dy = p[0] - cx, p[1] - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


def symbole(couleur, cote: int = 4096) -> Image.Image:
    """Le logo, recadré au plus près avec 2 % de marge, dans un carré transparent."""
    arc = _points_arc()
    formes = [[_tourner(p, r) for p in arc] for r in ROTATIONS]
    xs = [p[0] for f in formes for p in f] + [CERCLE[0] - CERCLE[2], CERCLE[0] + CERCLE[2]]
    ys = [p[1] for f in formes for p in f] + [CERCLE[1] - CERCLE[2], CERCLE[1] + CERCLE[2]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    taille = max(x1 - x0, y1 - y0)
    echelle = cote * 0.96 / taille
    ox = (cote - (x1 - x0) * echelle) / 2 - x0 * echelle
    oy = (cote - (y1 - y0) * echelle) / 2 - y0 * echelle
    im = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for f in formes:
        d.polygon([(ox + px * echelle, oy + py * echelle) for px, py in f], fill=couleur)
    cx, cy, r = ox + CERCLE[0] * echelle, oy + CERCLE[1] * echelle, CERCLE[2] * echelle
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=couleur)
    return im


def ecrire(dossier: Path, prefixe: str, im: Image.Image) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, cote in (("icon", 256), ("icon@2x", 512), ("logo", 256), ("logo@2x", 512)):
        im.resize((cote, cote), Image.LANCZOS).save(dossier / f"{prefixe}{nom}.png", optimize=True)


def principal() -> None:
    clair, sombre = symbole(NOIR), symbole(CLAIR)
    for dossier in (RACINE / "custom_components" / "sbg_energy_export" / "brand",
                    RACINE / "docs" / "brands" / "custom_integrations" / "sbg_energy_export"):
        ecrire(dossier, "", clair)
        ecrire(dossier, "dark_", sombre)
    icone = RACINE / "docs" / "icone"
    icone.mkdir(parents=True, exist_ok=True)
    clair.resize((256, 256), Image.LANCZOS).save(icone / "icon.png", optimize=True)
    clair.resize((512, 512), Image.LANCZOS).save(icone / "icon@2x.png", optimize=True)
    (icone / "icon.svg").write_text(SVG, encoding="utf-8")
    print("images de marque écrites")


if __name__ == "__main__":
    principal()
