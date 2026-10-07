# Journal des versions / Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions : [SemVer](https://semver.org/lang/fr/).
Le format de fichier « SBG HA export » a sa propre version (voir `docs/FORMAT_SBG_HA_EXPORT.md`).

## [0.5.0] — première version publique

- Lien **Télécharger** de la notification ouvert dans un nouvel onglet : il télécharge
  vraiment le fichier (le frontend l'interceptait comme une navigation interne).
- Format « SBG HA export » **version 2** aux pas de 5 et 15 min : une heure du passé reste en
  une ligne `mesure_60min` (ou `trou_60min`) au lieu de 4 ou 12 lignes ; export manuel dans une
  **archive ZIP** (environ 80 fois plus petit qu'avant pour trois ans à 5 min). Le pas de 60 min
  et l'envoi direct restent en version 1.
- Nouvelles catégories **ventilation** et **pompe** (pompes et traitement de l'eau) ; règles de
  catégorie affinées (PoE, ECS avant PAC, UV + eau).
- Interface traduite en **néerlandais** et en **allemand** (en plus du français et de l'anglais),
  y compris les phrases de l'écran de sélection.
- Supprimer l'intégration **retire l'autorisation** chez SBG Energy si l'envoi direct était
  connecté.
- README : confidentialité et RGPD, désinstallation ; `SECURITY.md` ; intégration continue
  (hassfest, HACS, tests).

## [0.4.0]

- Envoi direct : **code postal** obligatoire et case facultative « Améliorer les outils SBG »
  (décochée par défaut) ; 3 installations au plus par compte.
- Stockage local : les mois à 5 min de plus de 12 mois sont regroupés au quart d'heure.
- Images de marque locales (`brand/`, Home Assistant 2026.3 et plus).

## [0.3.0]

- **Envoi direct** facultatif vers analyse.sbg-energy.com, **désactivé par défaut** : connexion
  du compte par OAuth 2.0 « Device Authorization Grant » (aucun mot de passe dans Home
  Assistant), synchronisation des seuls jours manquants, au plus un envoi par mois ; services
  `envoyer` et `reimporter`, bouton « Envoyer maintenant », capteur « Dernier envoi ».

## [0.2.0]

- Stockage local compressé (un fichier par mois, mois terminés en `.csv.gz`), durée de
  conservation réglable, seulement les sources et les appareils choisis ; option « pas plus
  fin : 5 minutes ». Catégories étendues et sélection classée et recommandée. Licence Apache-2.0.

## [0.1.0]

- Export ouvert « SBG HA export » du tableau Énergie : configuration par l'interface, choix des
  appareils, enregistrement au quart d'heure, service `exporter`, téléchargement par lien signé
  servi par Home Assistant. Script manuel `outils/sbg_ha_export.py`.
