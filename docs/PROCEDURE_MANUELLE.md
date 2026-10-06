# Exporter vos données Home Assistant pour analyse.sbg-energy.com — procédure manuelle

*Mise à jour du 06/10/2026 : le chemin « téléchargements du tableau Énergie par tranches de
3 jours » est retiré (inutilisable : environ 120 téléchargements pour un an) ; l'export de
l'intégration « Import Statistics » (klausj1) le remplace comme chemin sans jeton.*

Pour qui : vous avez **Home Assistant** et son **tableau de bord Énergie** configuré (réseau, et
peut-être panneaux, batterie, appareils suivis). Vous n'avez pas de compteur communicant, ou vous
ne voulez pas ouvrir l'accès chez votre gestionnaire de réseau.

Ce que vous obtenez : un fichier que vous déposez **vous-même** sur
<https://sbg-energy.com/donnees-compteur/> (service analyse.sbg-energy.com). Rien n'est envoyé
automatiquement, à personne.

Deux chemins, sans installer notre intégration :

| | A. Intégration « Import Statistics » | B. Petit script avec un jeton |
|---|---|---|
| Jeton d'accès | aucun | un jeton que **vous** créez, et supprimez ensuite |
| Il faut | HACS et l'intégration Import Statistics (gratuite, de klausj1) | Python 3.9 ou plus récent sur l'ordinateur, et le script `sbg_ha_export.py` |
| Travail | un appel d'action dans Home Assistant, puis récupérer le fichier | une commande |
| Résultat | l'heure, sur la période choisie (CSV ou TSV d'Import Statistics, déposé tel quel) | fichier « SBG HA export » : l'heure depuis le début, et le quart d'heure des ~10 derniers jours |

> Les libellés de menus peuvent varier un peu selon la version de Home Assistant.

---

## Ce qu'il faut savoir avant de commencer : la limite du quart d'heure

Home Assistant garde :

- les statistiques **horaires** pour toujours ;
- les statistiques de **5 minutes** pendant **10 jours** seulement (réglage `purge_keep_days` du
  recorder), puis il les efface.

Donc :

- **pour le passé, vous aurez des heures**, pas des quarts d'heure ; le service le sait et adapte
  son analyse ;
- **le quart d'heure n'existe que pour les ~10 derniers jours** ;
- pour avoir du quart d'heure sur la durée, il faut l'**enregistrer au fil de l'eau** : c'est ce
  que fait l'intégration `sbg_energy_export`, à partir du jour où vous l'installez (voir son
  README ; pas encore publiée au 06/10/2026). Augmenter `purge_keep_days` marche aussi, mais fait
  grossir la base de Home Assistant de tous les capteurs, pas seulement de l'énergie.

---

## Avant tout : vérifier ce que suit votre tableau Énergie

1. Ouvrez **Paramètres → Tableaux de bord → Énergie** (ou l'icône Énergie du menu, puis ⋮ →
   *Configuration de l'énergie*).
2. Notez ce qui est configuré : **Réseau électrique** (prélèvement, et injection si vous avez des
   panneaux), **Panneaux solaires**, **Batterie domestique**, **Consommation d'appareils
   individuels**. Ce sont des **compteurs d'énergie cumulée** (kWh ou Wh).
3. Facultatif : **Outils de développement → Statistiques** liste toutes les statistiques à long
   terme et leurs éventuels problèmes (unité changée, capteur disparu). Cet outil sert à
   **vérifier et corriger**, il **n'exporte rien**. Si une statistique d'énergie y montre un
   problème, corrigez-le d'abord, sinon il se retrouvera dans le fichier.

---

## Chemin A — sans jeton : l'intégration « Import Statistics »

[Import Statistics](https://github.com/klausj1/homeassistant-statistics) (klausj1, version
5.3.0, Home Assistant 2026.1 ou plus récent) exporte les statistiques à long terme, donc
**horaires**, dans un fichier CSV ou TSV.

1. Installez **Import Statistics** par HACS, redémarrez Home Assistant, puis **Paramètres →
   Appareils et services → Ajouter une intégration → Import Statistics**.
2. Ouvrez **Outils de développement → Actions**, passez en mode YAML et collez :

   ```yaml
   action: import_statistics.export_statistics
   data:
     filename: sbg_export.csv
     entities:
       - sensor.mon_compteur_prelevement
       - sensor.mon_compteur_injection
     start_time: "2025-10-01 00:00:00"
     end_time: "2026-10-01 00:00:00"
     decimal: "."
     counter_fields: sum
   ```

   - `entities` : les capteurs d'énergie cumulée du tableau Énergie (une ligne par capteur ;
     ajoutez le solaire, la batterie ou des appareils si vous voulez ; les motifs avec `*` sont
     permis, mais pas `*` seul). Le service reconnaît leur rôle par le contenu et vous le demande
     si c'est ambigu.
   - `start_time` / `end_time` : en heure locale de Home Assistant, heures pleines, entre
     guillemets. Prenez **au moins un an**. Sans ces deux champs, l'export prend tout
     l'historique.
   - `counter_fields: sum` : colonnes `sum` et `state` (sans `delta`).
   - Ne changez pas `datetime_format` (défaut `%d.%m.%Y %H:%M`) : le service le lit tel quel.
     Le séparateur suit l'extension (`,` pour `.csv`, tabulation pour `.tsv`) ; `decimal` peut
     être `"."` ou `","`.
3. Cliquez sur « Exécuter l'action ». Le fichier est écrit dans le **dossier de configuration** de
   Home Assistant. Récupérez-le avec le module complémentaire **File editor**, **Samba share** ou
   **Studio Code Server**, ou par SSH.
4. Déposez-le **tel quel** sur le site, sans l'ouvrir dans Excel.

Ce que vous obtenez : **l'heure**, sur la période choisie. Le fichier contient les identifiants de
vos capteurs (`statistic_id`) : le service les lit pour reconnaître les rôles (prélèvement,
injection…), puis **ne garde que les rôles, aucun nom de capteur**.

---

## Chemin B — avec un jeton que vous créez vous-même

Le script `sbg_ha_export.py` (un seul fichier, bibliothèque standard de Python seulement) ne parle
qu'à **votre** Home Assistant et fabrique un fichier « SBG HA export ». Il n'est pas encore
publié : il est remis sur demande (contact@sbg-energy.com).

> Python : sous Windows, depuis python.org ou le Microsoft Store ; sous macOS et Linux, il est
> souvent déjà là (`python3 --version`).

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
   de chacun (`voiture`, `pac`, `ballon`, `cuisson`, `lavage`, `froid`, `informatique`, `eclairage`,
   `autre`) ;
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
**le quart d'heure des ~10 derniers jours**. Le fichier ne contient ni nom d'appareil ni
identifiant de capteur.

---

## Déposer le fichier

Sur <https://sbg-energy.com/donnees-compteur/>, déposez le fichier d'Import Statistics (chemin A)
ou `sbg_ha_export.csv` (chemin B). Le service vérifie le fichier (pas régulier, bilan de la
maison, appareils ≤ consommation…) et vous dit ce qu'il a pu en tirer. Il ne garde que les
rôles (prélèvement, injection, solaire, batterie, appareils sous une catégorie), jamais les noms
de capteurs ni d'appareils.

## Questions fréquentes

- **« Mon fichier a des lignes `trou` »** (chemin B) : Home Assistant n'avait pas de données
  (arrêt, capteur indisponible). Le service en tient compte.
- **« La consommation est vide sur certaines heures »** (chemin B) : un des compteurs (réseau,
  solaire, batterie) manquait ou a fait un saut impossible ; l'heure n'est pas inventée.
- **« L'export Import Statistics est vide »** : vérifiez les noms de capteurs (ceux du tableau
  Énergie) et que `start_time` / `end_time` sont des heures pleines entre guillemets.
- **« Je veux du quart d'heure sur un an »** : il faut l'enregistrer à partir de maintenant
  (intégration `sbg_energy_export`). Home Assistant ne l'a pas gardé.
