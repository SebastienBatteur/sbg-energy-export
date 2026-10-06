# Exporter vos données Home Assistant pour analyse.sbg-energy.com — procédure manuelle

Pour qui : vous avez **Home Assistant** et son **tableau de bord Énergie** configuré (réseau, et
peut-être panneaux, batterie, appareils suivis). Vous n'avez pas de compteur communicant, ou vous
ne voulez pas ouvrir l'accès chez votre gestionnaire de réseau.

Ce que vous obtenez : un fichier **« SBG HA export »** (CSV) que vous déposez **vous-même** sur
analyse.sbg-energy.com. Rien n'est envoyé automatiquement, à personne.

Deux chemins, sans rien installer dans Home Assistant :

| | A. Téléchargements du tableau Énergie | B. Petit script avec un jeton |
|---|---|---|
| Jeton d'accès | aucun | un jeton que **vous** créez, et supprimez ensuite |
| Travail | un téléchargement par tranche de 3 jours (≈ 120 pour un an) | une commande |
| Résultat | l'heure, sur la période téléchargée | l'heure depuis le début, et le quart d'heure des ~10 derniers jours |
| Il faut | Python 3.9 ou plus récent sur l'ordinateur | Python 3.9 ou plus récent sur l'ordinateur |

Dans les deux cas, le script `sbg_ha_export.py` (un seul fichier, bibliothèque standard de
Python seulement) fabrique le fichier final. Il ne parle qu'à **votre** Home Assistant (chemin B),
ou à rien du tout (chemin A).

> Les libellés de menus peuvent varier un peu selon la version de Home Assistant.
>
> Python : sous Windows, depuis python.org ou le Microsoft Store ; sous macOS et Linux, il est
> souvent déjà là (`python3 --version`).

---

## Ce qu'il faut savoir avant de commencer : la limite du quart d'heure

Home Assistant garde :

- les statistiques **horaires** pour toujours ;
- les statistiques de **5 minutes** pendant **10 jours** seulement (réglage `purge_keep_days` du
  recorder), puis il les efface.

Donc :

- **pour le passé, vous aurez des heures**, pas des quarts d'heure ; le service le sait (chaque
  ligne porte sa provenance) et adapte son analyse ;
- **le quart d'heure n'existe que pour les ~10 derniers jours** ;
- pour avoir du quart d'heure sur la durée, il faut l'**enregistrer au fil de l'eau** : c'est ce
  que fait l'intégration `sbg_energy_export`, à partir du jour où vous l'installez (voir son
  README). Augmenter `purge_keep_days` marche aussi, mais fait grossir la base de Home Assistant
  de tous les capteurs, pas seulement de l'énergie.

---

## Avant tout : vérifier ce que suit votre tableau Énergie

1. Ouvrez **Paramètres → Tableaux de bord → Énergie** (ou l'icône Énergie du menu, puis ⋮ →
   *Configuration de l'énergie*).
2. Notez ce qui est configuré : **Réseau électrique** (prélèvement, et injection si vous avez des
   panneaux), **Panneaux solaires**, **Batterie domestique**, **Consommation d'appareils
   individuels**.
3. Facultatif : **Outils de développement → Statistiques** liste toutes les statistiques à long
   terme et leurs éventuels problèmes (unité changée, capteur disparu). Cet outil sert à
   **vérifier et corriger**, il **n'exporte rien**. Si une statistique d'énergie y montre un
   problème, corrigez-le d'abord, sinon il se retrouvera dans le fichier.

---

## Chemin A — sans jeton : les téléchargements du tableau Énergie

1. Ouvrez le **tableau de bord Énergie**.
2. En haut, choisissez une **période de 1 à 3 jours** (cliquez sur la date, choisissez *Jour*, ou
   une plage personnalisée de 3 jours au plus). Au-delà de 3 jours, Home Assistant passe au jour
   et le fichier ne sert plus.
3. Menu **⋮** en haut à droite → **Télécharger les données** (*Download data* si votre interface est en anglais). Vous obtenez `energy.csv`.
4. Recommencez pour chaque tranche voulue. Renommez les fichiers au fur et à mesure
   (`energy_2026-01-01.csv`, `energy_2026-01-04.csv`…) dans un même dossier.
5. Dans ce dossier, avec `sbg_ha_export.py` :

   ```
   python sbg_ha_export.py --depuis-csv energy_*.csv --appareil sensor.ma_borne=voiture --appareil sensor.ma_pac=pac
   ```

   - `--appareil statistique=catégorie` pour **chaque** appareil que vous voulez inclure, avec sa
     catégorie : `voiture`, `pac`, `ballon`, `cuisson` ou `autre`. Les identifiants
     (`sensor.…`) sont dans la première colonne de `energy.csv`, lignes `device_consumption`.
   - Sans `--appareil` : aucun appareil (seulement réseau, solaire, batterie, maison).
6. Le script écrit `sbg_ha_export.csv`. C'est **ce fichier-là** que vous déposez, **pas**
   les `energy.csv` : ceux-ci contiennent les identifiants de vos capteurs (souvent le nom de la
   pièce ou de l'appareil), que le service n'a pas besoin de connaître.

Ce que vous obtenez : **l'heure**, sur les jours téléchargés.

---

## Chemin B — avec un jeton que vous créez vous-même

### 1. Créer le jeton

1. Dans Home Assistant, cliquez sur **votre nom** en bas à gauche (profil) → onglet **Sécurité**.
2. Tout en bas, **Jetons d'accès longue durée** (*Long-lived access tokens*) → **Créer un jeton**, nom : `export SBG`.
3. **Copiez** le jeton affiché (il ne sera plus montré).

Ce jeton donne **tous vos droits** sur Home Assistant : ne le donnez **à personne**, ne
l'envoyez pas par courriel, ne le collez pas sur un site. SBG Energy ne vous le demandera jamais.
Le script le lit au clavier (rien ne s'affiche quand vous le collez), s'en sert pour lire vos
statistiques, et ne l'écrit nulle part.

### 2. Lancer le script

```
python sbg_ha_export.py --url http://homeassistant.local:8123
```

(remplacez l'adresse par celle que vous utilisez dans votre navigateur ; en HTTPS avec un
certificat auto-signé, ajoutez `--certificat-non-verifie`, sur votre réseau local seulement).

Le script :

1. demande le jeton (collez-le, puis Entrée) ;
2. lit la configuration du tableau Énergie et **liste vos appareils** (leurs noms restent sur
   votre ordinateur) ;
3. demande lesquels exporter : `tous`, `aucun`, ou leurs numéros (`1,3`) ; puis la **catégorie**
   de chacun (`voiture`, `pac`, `ballon`, `cuisson`, `autre`) ;
4. lit les statistiques **horaires** depuis le début, mois par mois ;
5. écrit `sbg_ha_export.csv`.

Options utiles :

- `--pas 15` : fichier au quart d'heure ; les **~10 derniers jours** y sont mesurés au quart
  d'heure (`mesure_15min`), le reste est fait d'heures réparties en 4 (`heure_repartie`) ;
- `--pas 5` : même chose au pas de 5 minutes (`mesure_5min` ; heures réparties en 12) ; plus
  fin, utile pour reconnaître les démarrages et les cycles des appareils ;
- `--debut 2025-10-01 --fin 2026-10-01` : une période précise (dates UTC, fin exclue) ;
- `--appareils 1,3 --categorie 1=voiture --categorie 3=pac` : sans questions ;
- `--sortie mon_fichier.csv`.

Pour ne pas taper le jeton, vous pouvez le mettre dans la variable d'environnement
`SBG_HA_JETON` le temps de la commande ; ne l'écrivez pas dans un fichier.

### 3. Supprimer le jeton

Profil → **Sécurité** → **Jetons d'accès longue durée** → supprimez `export SBG`. Recréez-en un
la prochaine fois.

Ce que vous obtenez : **l'heure depuis le début** de vos statistiques, et avec `--pas 15`,
**le quart d'heure des ~10 derniers jours**.

---

## Déposer le fichier

Sur analyse.sbg-energy.com, déposez `sbg_ha_export.csv`. Le service vérifie le fichier (pas
régulier, bilan de la maison, appareils ≤ consommation…) et vous dit ce qu'il a pu en tirer.
Les appareils deviennent des équipements **déclarés** de votre maison (voiture, pompe à chaleur…),
sans leur nom.

## Questions fréquentes

- **« Mon fichier a des lignes `trou` »** : Home Assistant n'avait pas de données (arrêt, capteur
  indisponible). Le service en tient compte.
- **« La consommation est vide sur certaines heures »** : un des compteurs (réseau, solaire,
  batterie) manquait ou a fait un saut impossible ; l'heure n'est pas inventée.
- **« Je veux du quart d'heure sur un an »** : il faut l'enregistrer à partir de maintenant
  (intégration `sbg_energy_export`). Home Assistant ne l'a pas gardé.
