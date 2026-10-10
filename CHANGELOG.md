# Journal des versions / Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions : [SemVer](https://semver.org/lang/fr/).
Le format de fichier « SBG HA export » a sa propre version (voir `docs/FORMAT_SBG_HA_EXPORT.md`).

## [0.6.0] — votre logement

- Étape **Envoi** (fr, en, nl, de) : les données envoyées sont une source de **votre logement** et
  servent au **rapport de votre logement** ; trois logements et trois installations au plus par
  compte, une seule par logement. La phrase de conservation reste celle de 0.5.1 (« tout supprimé
  après 3 ans glissants ») : la nouvelle phrase du service viendra avec son étape suivante. L'information des occupants reste, en paragraphe à part.
- **Gestionnaire de réseau** (ORES, RESA, AIEG, AIESH, REW, Sibelga, Fluvius), champ **facultatif**
  de l'étape Envoi, « Je ne sais pas » par défaut. Il part avec les réglages seulement s'il est
  choisi ; sinon le service garde celui qu'il connaît ou le déduit du code postal quand il est
  certain. L'intégration ne le pré-remplit pas : une déduction faite ici passerait pour une
  déclaration.
- **Logement** : après la connexion du compte, une étape dit à quel logement les données arrivent
  et, si le compte en a plusieurs, laisse en choisir un autre (liste déroulante, aussi dans
  l'étape Envoi ensuite). Seulement si le service donne ces informations (champs facultatifs
  `logement` et `logements` de sa réponse) ; sinon, rien ne change : le service range par code
  postal, comme avec 0.5.
- **Installation effacée** depuis le compte (réponse `installation_effacee`) : l'envoi est coupé,
  une notification persistante et l'étape Envoi le disent, et l'intégration ne réessaie plus
  chaque jour. Le recocher, après avoir autorisé l'installation à nouveau depuis le compte, le
  reprend.
- **Installation déconnectée** depuis le compte (réponse `installation_deconnectee`) : l'intégration
  réessaie chaque jour, comme avant, mais ne le dit qu'**une fois** (notification dédiée, retirée
  dès que le service accepte de nouveau l'installation ou que l'envoi est désactivé), au lieu d'un
  « Rien n'a été envoyé » chaque matin.
- Les réglages envoyés au service nomment le **texte accepté** (`texte_consentement`), pour la
  preuve qu'il garde.
- **Exporter** : tant que l'envoi automatique n'est pas actif, la notification de l'export rappelle,
  dans la langue de Home Assistant, qu'il évite de déposer le fichier à la main chaque mois.
- README fr/en : lien vers la présentation et le mode d'emploi sur sbg-energy.com.
- L'envoi direct reste en **version 1** du format (le service ne range que des jours complets au
  pas de la session) ; la version 2 compacte reste réservée à l'export manuel.
- Corrigé : le **passage du collecteur** (toutes les 15 minutes) est maintenant une tâche de fond
  suivie, annulée au déchargement de l'intégration et à l'arrêt de Home Assistant. Avant, un passage
  en cours à ce moment-là continuait seul et interrogeait encore le recorder déjà fermé (erreur
  « cannot schedule new futures after shutdown » dans le journal).
- Corrigé : une installation **déconnectée puis effacée** depuis le compte ne garde plus la
  notification « installation déconnectée » (qui promettait un nouvel essai chaque jour) quand le
  refus arrive par l'étape Envoi : il ne reste que « envoi coupé ».

## [0.5.1] — logo visible dans HACS

- README (fr, en) : le logo est donné par une adresse absolue ; HACS n'affichait que le texte
  « Logo SBG Energy », faute de pouvoir charger une image à chemin relatif.

## [0.5.0] — première version publique

- Étape **Envoi** (fr, en, nl, de) : une phrase informe que les données de consommation peuvent refléter
  l'activité des personnes vivant dans le logement, et invite à les informer si le logement est partagé.
  Même phrase que sur le site et le service d'analyse. Sans URL (règle de hassfest).

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
