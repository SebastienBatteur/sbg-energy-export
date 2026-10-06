# SBG Energy Export (Home Assistant)

*[English version](README.en.md)*

Exporte les données du **tableau de bord Énergie** de Home Assistant au format ouvert
**« SBG HA export »** ([spécification](docs/FORMAT_SBG_HA_EXPORT.md)), pour les déposer vous-même
sur un service d'analyse comme analyse.sbg-energy.com.

- **Rien n'est envoyé nulle part.** L'intégration ne fait aucun appel réseau sortant : vous
  téléchargez le fichier depuis votre Home Assistant et vous le déposez où vous voulez.
- **Le strict nécessaire** : réseau (prélèvement, injection), solaire, batterie (charge,
  décharge), consommation de la maison, et les appareils que **vous** choisissez (tous, aucun,
  ou une sélection), sous un nom neutre (`voiture_1`, `pac_1`…). Ni nom d'appareil, ni pièce, ni
  identifiant d'entité, ni position.
- **Le quart d'heure à partir de l'installation** : Home Assistant n'efface pas ses statistiques
  horaires, mais efface ses statistiques de 5 minutes après 10 jours (`purge_keep_days`).
  L'intégration enregistre donc chaque quart d'heure au fil de l'eau.

> Statut : **version 0.1.0, pas encore publiée**. Nom, licence et publication à décider.

## Ce que contient l'export

| Période | Résolution | Provenance dans le fichier |
|---|---|---|
| Avant l'installation (depuis le début de vos statistiques) | l'heure | `mesure_60min`, ou `heure_repartie` dans un fichier au quart d'heure |
| ~10 jours avant l'installation, et depuis | le quart d'heure | `mesure_15min` |
| Données absentes | — | `trou` (cellules vides) |

Une cellule vide veut dire « inconnu », jamais zéro.

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
2. **Catégorie** de chaque appareil retenu : voiture électrique, pompe à chaleur, ballon d'eau
   chaude, cuisson, autre. Une catégorie est proposée d'après le nom ; corrigez-la si besoin.

Modifiable ensuite par **Configurer** sur la carte de l'intégration.

## Utilisation

- Boutons **Exporter (15 min)** et **Exporter (horaire)** sur l'appareil *SBG Energy Export* ;
- ou le service `sbg_energy_export.exporter` (champs `pas` : 15 ou 60, `debut`, `fin` : dates
  UTC, fin exclue) ; il rend le nom du fichier et le lien.

Une **notification** donne un lien **Télécharger**, servi par votre Home Assistant et valable une
heure. Le fichier reste dans `<config>/sbg_energy_export/exports/`.

Le capteur de diagnostic **Dernier quart d'heure enregistré** montre que l'enregistrement tourne
(attribut : premier quart d'heure enregistré).

## Ce qui est stocké chez vous

- `<config>/sbg_energy_export/quarts/quarts_AAAA-MM.csv` : un fichier par mois, une ligne par
  quart d'heure et par statistique du tableau Énergie (`debut_utc,statistique,kwh`), soit environ
  20 Mo par an pour 10 statistiques. Ces fichiers contiennent les identifiants de vos capteurs :
  ils restent dans Home Assistant, comme sa propre base de données. Toutes les statistiques du
  tableau sont enregistrées, pour que vous puissiez changer votre sélection plus tard sans perdre
  l'historique ; la sélection et l'anonymisation s'appliquent à l'export.
- `<config>/sbg_energy_export/exports/` : les exports produits (à supprimer quand vous voulez).
- `.storage/sbg_energy_export.collecteur` : le dernier quart d'heure traité.

Au démarrage, l'intégration rattrape les quarts d'heure manquants tant que Home Assistant a
encore leurs statistiques de 5 minutes (~10 jours) : un arrêt plus long laisse un trou, rempli à
l'export par l'heure répartie.

## Sans installer l'intégration

Voir [docs/PROCEDURE_MANUELLE.md](docs/PROCEDURE_MANUELLE.md) et le script
[`outils/sbg_ha_export.py`](outils/sbg_ha_export.py) (Python 3.9+, bibliothèque standard
seulement) : à partir des téléchargements du tableau Énergie, ou avec un jeton d'accès que vous
créez vous-même.

## Développement

- `custom_components/sbg_energy_export/sbg_format.py` : le format, en Python pur, partagé avec le
  script manuel (`outils/assembler_script.py` en recopie le bloc ; un test vérifie qu'ils sont
  identiques).
- Tests : `pytest` avec `pytest-homeassistant-custom-component` (Linux ou WSL ; Home Assistant ne
  tourne pas sous Windows), un vrai recorder SQLite en mémoire :

  ```
  pip install -r requirements_test.txt
  pytest
  ```

## Licence

Proposée : MIT (voir [LICENSE](LICENSE)), à confirmer.
