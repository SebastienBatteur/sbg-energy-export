# SBG Energy Export (Home Assistant)

*[English version](README.en.md)*

Exporte les données du **tableau de bord Énergie** de Home Assistant au format ouvert
**« SBG HA export »** ([spécification](docs/FORMAT_SBG_HA_EXPORT.md)), pour les déposer vous-même
sur un service d'analyse comme analyse.sbg-energy.com.

- **Rien n'est envoyé nulle part, par défaut.** L'export se télécharge depuis votre Home
  Assistant et vous le déposez où vous voulez. L'**envoi direct** à analyse.sbg-energy.com
  ([plus bas](#envoi-direct-à-analysesbg-energycom-facultatif-désactivé-par-défaut)) est
  **désactivé par défaut** : seulement si vous l'activez et connectez votre compte SBG Energy.
- **Le strict nécessaire** : réseau (prélèvement, injection), solaire, batterie (charge,
  décharge), consommation de la maison, et les appareils que **vous** choisissez (tous, aucun,
  ou une sélection), sous un nom neutre (`voiture_1`, `pac_1`…). Ni nom d'appareil, ni pièce, ni
  identifiant d'entité, ni position.
- **Le quart d'heure dès l'installation** : Home Assistant n'efface pas ses statistiques
  horaires, mais efface ses statistiques de 5 minutes après 10 jours (`purge_keep_days`).
  L'intégration reprend ces ~10 jours à l'installation, puis enregistre chaque quart d'heure (ou,
  en option, chaque période de 5 minutes) au fil de l'eau.

> Statut : **version 0.3.0, pas encore publiée**. Nom, licence et publication à décider.

## Ce que contient l'export

| Période | Résolution | Provenance dans le fichier |
|---|---|---|
| Avant l'installation (depuis le début de vos statistiques) | l'heure | `mesure_60min`, ou `heure_repartie` (heure répartie en 4, ou en 12 au pas de 5 min) |
| ~10 jours avant l'installation, et depuis | le quart d'heure | `mesure_15min` |
| idem, avec l'option « pas plus fin : 5 minutes » | 5 minutes | `mesure_5min` (fichier à 5 min) |
| Données absentes | — | `trou` (cellules vides) |

Dès l'installation, un export contient donc tout le passé en horaire et les ~10 derniers jours au
pas fin. Une cellule vide veut dire « inconnu », jamais zéro.

## Installation

Il faut Home Assistant **2026.9** ou plus récent (testé avec 2026.10.0b0) et le **tableau
Énergie configuré** (au moins le réseau, ou le solaire, ou une batterie).

**Par HACS (dépôt personnalisé)** : HACS → ⋮ → *Dépôts personnalisés* → l'adresse de ce dépôt,
catégorie *Intégration* → installer *SBG Energy Export* → redémarrer Home Assistant.

**À la main** : copier le dossier `custom_components/sbg_energy_export` dans le dossier
`custom_components` de votre configuration → redémarrer Home Assistant.

Puis : **Paramètres → Appareils et services → Ajouter une intégration → SBG Energy Export**.

## Configuration

1. **Appareils à exporter** : *Tous*, *Aucun* ou *Une sélection* parmi les appareils individuels
   du tableau Énergie.
   L'écran les classe du plus utile au moins utile pour l'analyse : gros consommateurs et
   pilotables (voiture, PAC, eau chaude), puis cuisson et lavage, puis consommation de fond
   (froid, informatique, éclairage), avec une phrase sur l'intérêt de chacun ; les recommandés
   sont cochés par défaut, vous restez libre.
2. **Catégorie** de chaque appareil retenu : voiture / borne, PAC / chauffage, eau chaude,
   cuisson, lavage, froid, informatique et réseau, éclairage, autre. Elle est proposée par des
   règles fixes (sans IA) : le nom, puis l'appareil Home Assistant (nom, modèle, fabricant), puis
   la puissance typique (une heure à 5,5 kWh ou plus = recharge de voiture) ; corrigez-la si
   besoin.
3. **Conservation locale** (années, **3** par défaut) : les mois plus anciens sont supprimés.
4. **Pas plus fin : 5 minutes** (désactivé par défaut) : garde les périodes de 5 minutes au lieu
   des quarts d'heure. Une résolution plus fine aide à reconnaître les appareils (démarrages,
   cycles) ; elle prend environ 2,5 fois plus de place. L'export peut alors se faire à 5 ou
   15 minutes.

Modifiable ensuite par **Configurer** sur la carte de l'intégration.

## Utilisation

- Boutons **Exporter (15 min)** et **Exporter (horaire)** sur l'appareil *SBG Energy Export*,
  et **Exporter (5 min)** avec l'option des 5 minutes ;
- ou le service `sbg_energy_export.exporter` (champs `pas` : 5, 15 ou 60, `debut`, `fin` : dates
  UTC, fin exclue) ; il rend le nom du fichier et le lien.

Une **notification** donne un lien **Télécharger**, servi par votre Home Assistant et valable une
heure. Le fichier reste dans `<config>/sbg_energy_export/exports/`.

Le capteur de diagnostic **Dernier quart d'heure enregistré** montre que l'enregistrement tourne
(attribut : premier quart d'heure enregistré).

## Envoi direct à analyse.sbg-energy.com (facultatif, désactivé par défaut)

Au lieu de télécharger le fichier et de le déposer vous-même, l'intégration peut l'envoyer
**elle-même** au service d'analyse de SBG Energy. **Rien ne part tant que vous ne l'avez pas
activé ET connecté votre compte.** C'est le **seul appel réseau sortant** de l'intégration.

1. **Configurer** → dernière étape **« Envoi à analyse.sbg-energy.com »** → cocher **Envoyer à
   analyse.sbg-energy.com**, choisir le pas (15 min ou horaire ; 5 min avec l'option des
   5 minutes).
2. L'écran affiche un **lien** et un **code** : ouvrez le lien (sur votre téléphone ou votre
   ordinateur), connectez-vous à votre **compte SBG Energy** (avec votre code à 6 chiffres),
   saisissez le code et acceptez. C'est tout : **une seule fois**.
   - Aucun mot de passe ni secret n'est enregistré dans Home Assistant : seulement un **jeton**
     (un « laissez-passer » révocable) gardé dans l'entrée de configuration, jamais écrit dans
     les journaux.
3. Donnez votre **code postal** dans votre compte (page **Home Assistant** de
   analyse.sbg-energy.com) pour que le rapport se calcule.

Ce qui part, et quand :

- **Le même contenu que l'export manuel** : les appareils choisis, sans nom d'entité, au pas
  choisi ; jours UTC complets seulement.
- **Au plus un envoi automatique par mois**, à partir du 2 (le mois écoulé, et les jours qui
  manqueraient) ; la première fois, **tout l'historique** disponible (3 ans au plus). Avant
  chaque envoi, l'intégration demande au service les jours qu'il a déjà, et **n'envoie que les
  manquants**. La limite est **imposée par le service** : le bouton **Envoyer maintenant** (et le
  service `sbg_energy_export.envoyer`) y est soumis aussi.
- **Réimporter** (service `sbg_energy_export.reimporter`, champs `debut` et `fin`, dates UTC, fin
  exclue) : renvoie la période et **remplace** ces jours côté service (par exemple après avoir
  corrigé une statistique). **3 fois par mois** au plus.
- Une fois par semaine, l'intégration renouvelle son jeton auprès de **auth.sbg-energy.com**
  (sans aucune donnée) : sans cela, la connexion expirerait après 30 jours sans usage.

Ce que le service en fait : **le rapport de votre compte**, mis à jour à chaque envoi, et une
**alerte « meilleure offre »** par e-mail (sans aucune donnée de consommation) quand une offre
analysée est moins chère que votre contrat d'au moins 40 € et 5 % par an, deux mois de suite.
Données gardées **3 ans glissants**, effaçables depuis votre compte, effacées si vous supprimez
votre compte. **Gratuit pendant la bêta.** Conditions :
<https://analyse.sbg-energy.com/conditions/#home-assistant>.

Arrêter : décocher l'envoi (plus rien ne part), ou **Déconnecter mon compte SBG Energy** dans la
même étape (le jeton est oublié et retiré chez SBG Energy). Depuis votre compte, vous pouvez
aussi **déconnecter Home Assistant** et **effacer** ce qui a été envoyé.

Le capteur de diagnostic **Dernier envoi** donne la date du dernier envoi (attributs : prochain
envoi permis, jours envoyés).

## Ce qui est stocké chez vous

- `<config>/sbg_energy_export/mesures/mesures_15min_AAAA-MM.csv` (ou `mesures_5min_…`) : un
  fichier par mois (UTC), une ligne par période et une colonne par statistique. Le mois en cours
  est en clair ; chaque **mois terminé est compressé** (`.csv.gz`) ; l'export lit les deux sans
  que vous ayez rien à faire. Les mois plus anciens que la **durée de conservation** sont
  supprimés.
- **Seulement le nécessaire** : les sources réseau, solaire et batterie du tableau Énergie, et les
  appareils que vous avez choisis. Ces fichiers contiennent les identifiants de vos capteurs : ils
  restent dans Home Assistant, comme sa propre base de données ; l'anonymisation s'applique à
  l'export.
- **Appareil ajouté** plus tard : enregistré à partir de ce moment, et rattrapé sur les ~10 jours
  où Home Assistant a encore ses statistiques de 5 minutes. **Appareil retiré** : il n'est plus
  enregistré ni exporté ; ce qui a déjà été enregistré reste jusqu'à la fin de la durée de
  conservation (un historique fin ne se reconstruit pas, et un appareil décoché par erreur
  retrouve ainsi son passé).
- Place mesurée sur un an simulé, 10 appareils (`outils/mesurer_stockage.py`) : **≈ 0,4 Mo** au
  quart d'heure, **≈ 1 Mo** au pas de 5 minutes (jusqu'à ≈ 0,7 et 1,8 Mo avec des compteurs plus
  précis que le Wh).
- `<config>/sbg_energy_export/exports/` : les exports produits (à supprimer quand vous voulez).
- `.storage/sbg_energy_export.collecteur` : la dernière période traitée, les statistiques suivies.
- `.storage/sbg_energy_export.envoi` (envoi direct seulement) : date du dernier envoi et du prochain permis ; le jeton est dans l'entrée de configuration (`.storage/core.config_entries`), comme pour les autres intégrations.

Au démarrage, l'intégration rattrape les périodes manquantes tant que Home Assistant a encore
leurs statistiques de 5 minutes (~10 jours) : un arrêt plus long laisse un trou, rempli à l'export
par l'heure répartie. Les fichiers de la version 0.1.0 (`quarts/`) sont repris automatiquement.

## Sans installer l'intégration

Voir [docs/PROCEDURE_MANUELLE.md](docs/PROCEDURE_MANUELLE.md) :

- **sans jeton** : l'export horaire de l'intégration HACS
  [Import Statistics](https://github.com/klausj1/homeassistant-statistics) (klausj1) se dépose tel
  quel sur le service ;
- **avec un jeton** que vous créez vous-même : le script
  [`outils/sbg_ha_export.py`](outils/sbg_ha_export.py) (Python 3.9+, bibliothèque standard
  seulement) produit un fichier « SBG HA export ».

## Développement

- `custom_components/sbg_energy_export/sbg_format.py` : le format, en Python pur, partagé avec le
  script manuel (`outils/assembler_script.py` en recopie le bloc ; un test vérifie qu'ils sont
  identiques).
- `custom_components/sbg_energy_export/stockage.py` : le stockage local (Python pur).
- `outils/mesurer_stockage.py` : mesure de la place prise (stockage et export) sur un an simulé.
- `custom_components/sbg_energy_export/categories.py` : catégories proposées et appareils recommandés (règles fixes).
- `docs/icone/` : icône (SVG, PNG 256 et 512 px), dessin maison.
- Tests : `pytest` avec `pytest-homeassistant-custom-component` (Linux ou WSL ; Home Assistant ne
  tourne pas sous Windows), un vrai recorder SQLite en mémoire :

  ```
  pip install -r requirements_test.txt
  pytest
  ```

## Licence

[Apache-2.0](LICENSE) (voir aussi [NOTICE](NOTICE)).
