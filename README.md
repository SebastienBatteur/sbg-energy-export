# SBG Energy Export (Home Assistant)

<img src="https://raw.githubusercontent.com/SebastienBatteur/sbg-energy-export/main/docs/icone/icon.png" alt="Logo SBG Energy" width="96" height="96">

*[English version](README.en.md)*

Présentation et mode d'emploi : https://sbg-energy.com/donnees-compteur/#home-assistant

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

> Statut : **version 0.6.2, bêta**. Licence Apache-2.0. Interface en français, anglais, néerlandais
> et allemand. Problèmes et idées : [issues](https://github.com/SebastienBatteur/sbg-energy-export/issues) ;
> faille de sécurité : voir [SECURITY.md](SECURITY.md). Historique des versions : [CHANGELOG.md](CHANGELOG.md).

## Ce que contient l'export

| Période | Résolution | Provenance dans le fichier |
|---|---|---|
| Avant l'installation (depuis le début de vos statistiques) | l'heure | `mesure_60min` : une ligne par heure (version 2 du format, depuis 0.5.0 ; auparavant l'heure était répartie en 4 ou 12 lignes `heure_repartie`) |
| ~10 jours avant l'installation, et depuis | le quart d'heure | `mesure_15min` |
| idem, avec l'option « pas plus fin : 5 minutes » | 5 minutes | `mesure_5min` (fichier à 5 min) |
| Données absentes | — | `trou` (cellules vides) ; `trou_60min` pour une heure entière du passé |

Dès l'installation, un export contient donc tout le passé en horaire et les ~10 derniers jours au
pas fin. Une cellule vide veut dire « inconnu », jamais zéro.

## Installation

Il faut Home Assistant **2026.9** ou plus récent (testé avec 2026.10.0b0) et le **tableau
Énergie configuré** (au moins le réseau, ou le solaire, ou une batterie).

**Par HACS (dépôt personnalisé)** : HACS → ⋮ → *Dépôts personnalisés* → `https://github.com/SebastienBatteur/sbg-energy-export`,
catégorie *Intégration* → installer *SBG Energy Export* → redémarrer Home Assistant.

**À la main** : copier le dossier `custom_components/sbg_energy_export` dans le dossier
`custom_components` de votre configuration → redémarrer Home Assistant.

Puis : **Paramètres → Appareils et services → Ajouter une intégration → SBG Energy Export**.

## Configuration

1. **Appareils à exporter** : *Tous*, *Aucun* ou *Une sélection* parmi les appareils individuels
   du tableau Énergie.
   L'écran les classe du plus utile au moins utile pour l'analyse : gros consommateurs et
   pilotables (voiture, PAC, eau chaude), puis cuisson et lavage, puis consommation de fond
   (froid, informatique, éclairage, ventilation, pompes), avec une phrase sur l'intérêt de chacun ; les recommandés
   sont cochés par défaut, vous restez libre.
2. **Catégorie** de chaque appareil retenu : voiture / borne, PAC / chauffage, eau chaude,
   cuisson, lavage, froid, informatique et réseau, éclairage, ventilation, pompes et eau, autre.
   Elle est proposée par des règles fixes (sans IA) : le nom, puis l'appareil Home Assistant (nom,
   modèle, fabricant), puis la puissance typique (une heure à 5,5 kWh ou plus = recharge de
   voiture) ; corrigez-la si besoin. Les mots les plus précis gagnent : un « port PoE » de switch
   est toujours de l'informatique, « ECS » (eau chaude sanitaire) passe avant « PAC », « UV » avec
   « eau » est un traitement de l'eau et pas un éclairage ; « prise » ou « multiprise » ne décident
   rien seuls.
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
heure ; il s'ouvre dans un nouvel onglet, qui télécharge le fichier (si rien ne se passe : clic
droit → « Ouvrir dans un nouvel onglet »). Le fichier est une **archive ZIP** qui contient le CSV :
déposez-la telle quelle sur analyse.sbg-energy.com. Elle reste dans
`<config>/sbg_energy_export/exports/`.

Le capteur de diagnostic **Dernier quart d'heure enregistré** montre que l'enregistrement tourne
(attribut : premier quart d'heure enregistré).

## Envoi direct à analyse.sbg-energy.com (facultatif, désactivé par défaut)

Au lieu de télécharger le fichier et de le déposer vous-même, l'intégration peut l'envoyer
**elle-même** au service d'analyse de SBG Energy. **Rien ne part tant que vous ne l'avez pas
activé ET connecté votre compte.** C'est le **seul appel réseau sortant** de l'intégration.

1. **Configurer** → dernière étape **« Envoi à analyse.sbg-energy.com »** → cocher **Envoyer à
   analyse.sbg-energy.com**, donner votre **code postal** (obligatoire : Home Assistant ne le
   connaît pas ; il sert aux tarifs du réseau, à la région et à la météo de la zone, jamais à une
   adresse), si vous le connaissez votre **gestionnaire de réseau** (facultatif : « Je ne sais
   pas » par défaut, le service le déduit alors du code postal quand il n'y en a qu'un possible),
   choisir le pas (15 min ou horaire ; 5 min avec l'option des 5 minutes) et, si vous le voulez,
   cocher **Améliorer les outils SBG** (voir plus bas ; décoché par défaut).
2. L'écran affiche un **lien** et un **code** : ouvrez le lien (sur votre téléphone ou votre
   ordinateur), connectez-vous à votre **compte SBG Energy** (avec votre code à 6 chiffres),
   saisissez le code et acceptez. C'est tout : **une seule fois**.
   - Aucun mot de passe ni secret n'est enregistré dans Home Assistant : seulement un **jeton**
     (un « laissez-passer » révocable) gardé dans l'entrée de configuration, jamais écrit dans
     les journaux.
3. Le code postal et la case partent au service juste après la connexion : le rapport se
   calcule dès le premier envoi. **Trois installations Home Assistant au plus par compte** : la
   quatrième est refusée à cette étape (rien n'est activé, le jeton est retiré) ; vous pouvez en
   déconnecter une depuis votre compte. Changer le code postal, le gestionnaire ou la case plus
   tard, dans la même étape, fait un appel au service au moment où vous enregistrez (compte
   connecté).
4. **Votre logement** : les données rejoignent un logement de votre compte SBG Energy, et c'est
   son rapport qui en tient compte. Quand le service le dit, l'intégration affiche ce logement
   juste après la connexion et, si votre compte en a plusieurs, vous laisse en choisir un autre
   (ici, ou plus tard dans l'étape Envoi). Sinon, le service range l'installation d'après le code
   postal.

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
- **Pas de 5 minutes** : le service et l'intégration ne le gardent que 12 mois ; les jours plus
  anciens partent au quart d'heure, dans le même envoi.
- **500 Mo au plus** par compte côté service (un message clair le dit au-delà).
- Une fois par semaine, l'intégration renouvelle son jeton auprès de **auth.sbg-energy.com**
  (sans aucune donnée) : sans cela, la connexion expirerait après 30 jours sans usage.

Ce que le service en fait : **le rapport de votre logement**, mis à jour à chaque envoi, et une
**alerte « meilleure offre »** par e-mail (sans aucune donnée de consommation) quand une offre
analysée est moins chère que votre contrat d'au moins 40 € et 5 % par an, deux mois de suite.
Le pas de 5 minutes y est gardé **12 mois** (pour comprendre les comportements), puis regroupé au
quart d'heure (pour suivre leur évolution) ; tout est supprimé après **3 ans glissants**,
effaçable depuis votre compte, effacé si vous supprimez votre compte. **Gratuit pendant la
bêta.**

**Améliorer les outils SBG** (case facultative, **décochée par défaut**, la même que sur le
formulaire de dépôt : « J'accepte que SBG garde mes données de consommation, pseudonymisées, pour
améliorer ses outils (simulateur, SBG Home). Je peux retirer cet accord à tout moment. ») :
**seulement si vous la cochez**, chaque mois reçu sert, 90 jours après sa réception, aux
**statistiques par code postal** (totaux mensuels sans nom, publiés à partir de 10 foyers) et à
une **copie pseudonymisée** de la courbe du mois. Sans la case, rien de tout cela. La décocher (ici
ou dans votre compte) efface les copies ; les totaux déjà versés, anonymes, ne peuvent plus être
retrouvés. Conditions :
<https://analyse.sbg-energy.com/conditions/#home-assistant>.

Arrêter : décocher l'envoi (plus rien ne part), ou **Déconnecter mon compte SBG Energy** dans la
même étape (le jeton est oublié et retiré chez SBG Energy). Depuis votre compte, vous pouvez
aussi **déconnecter Home Assistant** et **effacer** ce qui a été envoyé. Une installation
effacée depuis votre compte est refusée ensuite : l'intégration **coupe alors l'envoi** et le dit
(notification, et dans l'étape Envoi), sans réessayer chaque jour. Pour reprendre, autorisez-la à
nouveau depuis votre compte, puis recochez l'envoi.

Le capteur de diagnostic **Dernier envoi** donne la date du dernier envoi (attributs : prochain
envoi permis, jours envoyés).

## Ce qui est stocké chez vous

- `<config>/sbg_energy_export/mesures/mesures_15min_AAAA-MM.csv` (ou `mesures_5min_…`) : un
  fichier par mois (UTC), une ligne par période et une colonne par statistique. Le mois en cours
  est en clair ; chaque **mois terminé est compressé** (`.csv.gz`) ; l'export lit les deux sans
  que vous ayez rien à faire. Avec l'option des 5 minutes, les mois de **plus de 12 mois sont
  regroupés au quart d'heure** (version 0.4.0) ; les mois plus anciens que la **durée de
  conservation** (3 ans par défaut) sont supprimés.
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
  précis que le Wh). Sur **3 ans** avec l'option des 5 minutes (`--trois-ans`) : **2,84 Mo** tout à
  5 minutes, **1,74 Mo** avec le regroupement après 12 mois (39 % de moins).
- `<config>/sbg_energy_export/exports/` : les exports produits (à supprimer quand vous voulez).
- `.storage/sbg_energy_export.collecteur` : la dernière période traitée, les statistiques suivies.
- `.storage/sbg_energy_export.envoi` (envoi direct seulement) : date du dernier envoi et du prochain permis, derniers réglages vus chez le service (dont le nom du logement, s'il le donne) ; le jeton est dans l'entrée de configuration (`.storage/core.config_entries`), comme pour les autres intégrations.

Au démarrage, l'intégration rattrape les périodes manquantes tant que Home Assistant a encore
leurs statistiques de 5 minutes (~10 jours) : un arrêt plus long laisse un trou, rempli à l'export
par la ligne horaire. Les fichiers de la version 0.1.0 (`quarts/`) sont repris automatiquement.

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
- `custom_components/sbg_energy_export/brand/` : images de marque locales (logo officiel SBG
  Energy ; Home Assistant 2026.3 et plus), variantes `dark_*` pour le thème sombre ;
  `docs/brands/` : les mêmes, prêtes pour une demande au dépôt `home-assistant/brands` (pas
  soumise ; utile tant que HACS n'affiche pas les images locales) ; `docs/icone/` : l'icône du
  README. Tout est produit par `outils/icones_marque.py` à partir du SVG du site.
- Tests : `pytest` avec `pytest-homeassistant-custom-component` (Linux ou WSL ; Home Assistant ne
  tourne pas sous Windows), un vrai recorder SQLite en mémoire :

  ```
  pip install -r requirements_test.txt
  pytest
  ```

## Confidentialité et RGPD

- **Par défaut, rien ne quitte votre Home Assistant** : l'export est un fichier que vous
  téléchargez et déposez vous-même où vous voulez. L'intégration ne fait aucun appel réseau sortant
  tant que l'envoi direct n'est pas activé **et** votre compte connecté.
- **Ce qui part avec l'envoi direct** : uniquement le contenu de l'export (énergie par période du
  réseau, du solaire, de la batterie, de la maison et des appareils choisis sous un nom neutre),
  votre code postal, le gestionnaire de réseau s'il est choisi, le logement s'il est choisi dans
  la liste du service, la case « Améliorer les outils SBG », un identifiant aléatoire de
  l'installation et la version de l'intégration (en-tête `User-Agent`). Jamais de nom d'entité, de nom d'appareil, de pièce, d'adresse ni de position.
- **Responsable du traitement, finalités, durées de conservation, droits (accès, rectification,
  effacement, retrait du consentement) et contact** : voir les conditions du service,
  <https://analyse.sbg-energy.com/conditions/#home-assistant>. Vous pouvez effacer vos données et
  déconnecter Home Assistant depuis votre compte SBG Energy.
- **Chez vous** : les fichiers listés ci-dessus restent dans votre dossier de configuration ; ils
  font partie de vos sauvegardes Home Assistant.

## Désinstallation

1. **Paramètres → Appareils et services → SBG Energy Export → ⋮ → Supprimer**. Si l'envoi direct
   était connecté, l'intégration retire son autorisation chez SBG Energy (au mieux : sans réseau,
   le jeton est seulement oublié et expire après 30 jours sans usage ; vous pouvez aussi
   déconnecter Home Assistant depuis votre compte).
2. **HACS → SBG Energy Export → ⋮ → Supprimer** (ou effacer le dossier
   `custom_components/sbg_energy_export` si installé à la main), puis redémarrer Home Assistant.
3. **Données locales** : elles ne sont pas effacées automatiquement (ce sont vos données). Pour
   tout enlever, supprimer le dossier `<config>/sbg_energy_export/` et les fichiers
   `.storage/sbg_energy_export.collecteur` et `.storage/sbg_energy_export.envoi`
   (Home Assistant arrêté).
4. **Données envoyées** (envoi direct seulement) : à effacer depuis votre compte SBG Energy.

## Licence

[Apache-2.0](LICENSE) (voir aussi [NOTICE](NOTICE)). Le nom et le logo SBG Energy ne sont pas couverts
par la licence (section 6) : ils servent à identifier l'origine du projet.
