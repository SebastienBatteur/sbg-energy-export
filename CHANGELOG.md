# Journal des versions / Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions : [SemVer](https://semver.org/lang/fr/).
Le format de fichier « SBG HA export » a sa propre version (voir `docs/FORMAT_SBG_HA_EXPORT.md`).

## [0.6.2] — le recorder indisponible ne laisse plus d'erreur perdue

- Corrigé : une erreur du recorder pendant l'enregistrement des mesures fines (toutes les
  15 minutes, et au chargement de l'intégration) restait dans une tâche de fond que personne ne
  lisait. Elle ne ressortait dans le journal que plus tard (au passage suivant), sous la forme
  « Task exception was never retrieved », sans dire ce qu'il advenait des mesures. Elle est maintenant
  consignée tout de suite : un **avertissement** d'une ligne quand les statistiques de Home
  Assistant sont indisponibles (base fermée ou pas prête), une erreur avec sa trace pour le reste.
  Dans tous les cas le passage suivant reprend où le précédent s'est arrêté : aucune période
  n'est marquée comme enregistrée sans l'avoir été, **aucune mesure n'est perdue** (comme avant).
- Corrigé : plus aucune requête n'est envoyée au recorder quand il n'est pas en marche (base pas
  encore prête, démarrage du recorder en échec, recorder arrêté), y compris entre deux jours d'un
  rattrapage ; le passage s'arrête là et le suivant reprend. Avant, la requête partait quand même (« cannot schedule new futures after shutdown »).
- Tests : le test d'installation qui avance l'horloge laissait le minuteur du collecteur lancer
  son passage après la fin du test, pendant la fermeture du recorder de test (échec intermittent
  de la CI, « no such table: statistics_meta »). Il fait maintenant sonner le minuteur lui-même
  et attend la fin du passage.

## [0.6.1] — l'envoi et l'accord ne se retirent plus sans confirmation

- Corrigé : l'étape **Envoi** pouvait **couper l'envoi automatique et retirer l'accord « Améliorer
  les outils SBG »** sans que l'utilisateur l'ait voulu. Constaté sur une installation réelle juste
  après la mise à jour 0.5.1 → 0.6.0 (compte connecté, envoi actif, accord donné) : après le seul
  choix du gestionnaire de réseau, l'étape a été validée avec les deux interrupteurs décochés ;
  0.6.0 l'a pris tel quel, a retiré l'accord chez le service (qui efface alors les copies
  pseudonymisées) et a coupé l'envoi. L'intégration ne s'en remet plus aux seuls interrupteurs
  reçus :
  - un interrupteur reçu **décoché alors que l'étape le montrait coché** ouvre une étape
    **Confirmer** (fr, en, nl, de), une case par effet (« Désactiver l'envoi », « Retirer mon
    accord »), **décochées par défaut**. Ce qui n'est pas confirmé reste comme avant ; le reste de
    l'étape (code postal, gestionnaire de réseau, logement, pas) est enregistré. Rien ne part au
    service avant cette confirmation ;
  - la comparaison se fait avec ce que l'étape **montrait à son ouverture**, plus avec l'état relu
    au moment de valider : un accord donné entre-temps depuis le compte n'est plus retiré par un
    formulaire où la case, montrée décochée, n'a pas été touchée ; et un accord **retiré**
    entre-temps depuis le compte n'est jamais redonné : l'accord ne part « donné » que si la case
    est passée, dans ce formulaire, de décochée à cochée. Dans ce cas l'étape revient, case
    décochée, avec un message, et rien n'est enregistré avant une nouvelle validation ;
  - le code postal est vérifié sur l'état final de l'interrupteur d'envoi (un arrêt non confirmé
    laisse l'envoi actif, qui ne s'enregistre pas sans code postal) ;
  - un interrupteur absent de la saisie vaut ce qui était montré, jamais « décoché ».
  « Déconnecter mon compte SBG Energy » reste un geste direct, sans confirmation de plus (aucun
  réglage ne part alors au service).
- **Si 0.6.0 a décoché vos interrupteurs** : ouvrez Configurer → étape Envoi, recochez « Envoyer à
  analyse.sbg-energy.com » et, si vous l'aviez donné, « Améliorer les outils SBG », puis validez.
  L'envoi reprend à la prochaine échéance mensuelle (ou par le bouton « Envoyer maintenant ») ; les
  mesures gardées dans Home Assistant et les jours déjà reçus par le service n'ont pas été touchés.

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
- Corrigé : l'état de l'envoi (installation effacée, logement, prochain envoi permis) est lié à
  l'identifiant de l'installation et supprimé avec l'intégration : une intégration supprimée puis
  ajoutée de nouveau ne s'affiche plus « effacée » et ne reprend pas le logement de l'ancienne.
  De même à la **déconnexion du compte** et à la connexion d'un compte : l'état gardé (logement,
  liste des logements, réglages vus chez le service, dernier et prochain envoi) est oublié, pour
  qu'un autre compte ne retrouve pas le logement du précédent.
- **Installation effacée** : l'envoi est coupé quelle que soit la requête du service qui le dit
  (jours, réglages, ouverture, morceau, fermeture de la session, réimport), et plus seulement à
  l'ouverture de la session.

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
