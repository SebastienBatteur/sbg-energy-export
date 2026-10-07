# Format « SBG HA export » — versions 1 et 2

Format ouvert pour transmettre à un service d'analyse (analyse.sbg-energy.com) les données du
**tableau de bord Énergie** de Home Assistant : réseau, solaire, batterie, consommation de la maison
et, au choix de l'utilisateur, les appareils suivis.

Produit par :
- l'intégration Home Assistant `sbg_energy_export` (dépôt `sbg-energy-export`) ;
- le script manuel `sbg_ha_export.py` (même dépôt, dossier `outils/`), sans rien installer.

Lu par : `sbg_optimisation/tools/contrats/lecture/ha_export.py` (lecteur déterministe, sans IA).

Statut : **version 1, proposée le 06/10/2026**, étendue le même jour au **pas de 5 minutes**
(§ 3.5 : extension compatible, la version reste 1). **Version 2 le 07/10/2026** (§ 3.6) : dans
un fichier au pas de 5 ou 15 min, le passé connu seulement à l'heure reste en lignes horaires au
lieu d'être découpé en 4 ou 12 parts égales. Un vrai export de trois ans au pas de 5 min avec
plus de 20 appareils faisait 47,6 Mo en version 1 (≈ 330 000 lignes) : il fait ≈ 5 Mo en version 2
(≈ 35 000 lignes), ≈ 0,6 Mo dans un ZIP. Deux catégories d'appareils ajoutées le même jour
(`ventilation`, `pompe`, extension compatible des deux versions). Rien n'est figé tant que le
service ne l'a pas publiée ; toute évolution incompatible change le numéro de version.

---

## 1. Pourquoi ce format

Beaucoup de foyers n'ont pas de compteur communicant, ou n'ouvrent pas l'accès à leurs données
chez le gestionnaire de réseau, mais mesurent tout avec Home Assistant. Home Assistant sait
exporter ses données (tableau Énergie → « Télécharger les données », ou l'API WebSocket), mais :

- le fichier du tableau Énergie (`energy.csv`) contient les **identifiants d'entités**
  (`sensor.borne_garage`, `sensor.pac_salon`…) qui disent souvent la pièce, la marque ou
  l'emplacement ; il ne contient pas la consommation de la maison sous forme vérifiable ;
- il n'a qu'une résolution par fichier, choisie par la vue (heure pour 1 à 3 jours, jour au-delà) ;
- il ne dit pas ce qui est mesuré et ce qui manque.

Le format « SBG HA export » garde **le strict nécessaire**, dit **d'où vient chaque ligne**, et
permet au service de **vérifier** le fichier sans rien deviner.

## 2. Ce que Home Assistant garde vraiment (et la limite qui en découle)

Vérifié sur la documentation et le code de Home Assistant (version de développement d'octobre 2026) :

| Donnée | Résolution | Durée de conservation |
|---|---|---|
| États bruts (`states`) | chaque changement | `purge_keep_days`, **10 jours** par défaut |
| Statistiques **à court terme** (`statistics_short_term`) | **5 minutes** | purgées avec les états, après `purge_keep_days` (10 jours par défaut) |
| Statistiques **à long terme** (`statistics`) | **1 heure** | **jamais purgées** |

Sources : documentation du recorder (`purge_keep_days`, défaut 10 ; `auto_purge`, défaut vrai) ;
documentation développeur des capteurs (« long-term statistics », statistiques mises à jour
toutes les 5 minutes, agrégées à l'heure, `state_class` `total` / `total_increasing`) ; code du
recorder (`purge.py` : `find_short_term_statistics_to_purge(purge_before)` avec
`purge_before = maintenant − keep_days`).

**Conséquence** : sauf si l'utilisateur a augmenté `purge_keep_days`, il n'existe pas
d'historique au quart d'heure sur un an dans Home Assistant. On a :

- **l'heure pour le passé** (depuis que les capteurs existent) ;
- **le quart d'heure (ou les 5 minutes) des ~10 derniers jours** ;
- **le quart d'heure à partir de l'installation** de l'intégration, qui l'enregistre au fil de l'eau ;
  avec l'option « pas plus fin : 5 minutes », elle garde les périodes de 5 minutes telles quelles
  (une résolution plus fine aide à reconnaître les appareils : démarrages, cycles).

Le format le dit, ligne par ligne, avec la **provenance**.

## 3. Le fichier

- Texte **UTF-8** (BOM toléré à la lecture), fin de ligne **LF** (CRLF toléré), séparateur **virgule**,
  point décimal, aucun guillemet.
- Un **en-tête de métadonnées** : lignes commençant par `#`.
- Une **ligne d'en-tête de colonnes**, puis **une ligne par pas de temps** (version 1), ou par pas
  de temps mesuré et par heure du passé (version 2, § 3.6).
- Nom conseillé : `sbg_ha_export_AAAAMMJJ-HHMMSS_15min.csv` (ou `_60min`, `_5min`).
- **Compression** (07/10/2026) : le fichier peut voyager dans une archive **ZIP** qui ne contient
  que lui (`sbg_ha_export_…_5min.zip` → `sbg_ha_export_…_5min.csv`). L'intégration écrit ses
  exports ainsi depuis 0.5.0 ; le formulaire du service accepte déjà les ZIP (contrôles de taille,
  de chemins et de taux de compression). Le CSV dedans suit ce document à l'octet près.

### 3.1 Métadonnées

La première ligne est exactement `# SBG HA export`. Ensuite, des lignes `# clé: valeur` :

| Clé | Obligatoire | Valeur |
|---|---|---|
| `version` | oui | `1` ou `2` (§ 3.6) |
| `pas_minutes` | oui | `5`, `15` ou `60` ; en version 2 : le pas des lignes **mesurées au pas fin** (les lignes horaires durent une heure) |
| `fuseau` | oui | fuseau IANA de la maison (`Europe/Brussels`) ; les instants restent en UTC, le fuseau sert aux plages tarifaires et aux habitudes |
| `unite` | oui | `kWh` |
| `horodatage` | non | rappel : début de l'intervalle, UTC |
| `debut`, `fin` | non | premier instant, et fin exclue, en UTC |
| `debut_mesure_15min` | non | fichiers à 15 et 60 min : premier quart d'heure **mesuré**, ou `aucun` |
| `debut_mesure_5min` | non | fichiers à 5 min (à la place de la précédente) : première période de 5 min **mesurée**, ou `aucun` |
| `non_configure` | non | colonnes fixes absentes du tableau Énergie (pas de panneaux, pas de batterie…), séparées par des virgules ; ces colonnes sont **vides** dans tout le fichier et valent 0 dans le bilan |
| `generateur` | non | logiciel et version (`sbg_energy_export 0.1.0`) |
| `genere_le` | non | instant de production, UTC |
| `appareil` | une par appareil | `nom;categorie=…[;inclus_dans=nom_du_parent]` |

### 3.2 Colonnes, dans cet ordre

| Colonne | Contenu (kWh sur l'intervalle) |
|---|---|
| `debut_utc` | début de l'intervalle, `AAAA-MM-JJTHH:MM:SSZ` |
| `provenance` | voir § 3.3 |
| `prelevement_reseau` | énergie prise au réseau (somme de toutes les sources réseau du tableau) |
| `injection_reseau` | énergie rendue au réseau |
| `production_solaire` | production de toutes les sources solaires |
| `charge_batterie` | énergie entrée dans la (les) batterie(s) |
| `decharge_batterie` | énergie sortie de la (les) batterie(s) |
| `consommation_maison` | `prélèvement + production − injection − charge + décharge` (comme le tableau Énergie) |
| une colonne par appareil choisi | consommation de l'appareil |

**Appareils** : nom neutre `<catégorie>_<rang>` (`voiture_1`, `pac_1`, `pac_2`…), catégorie choisie
par l'utilisateur dans une **liste fermée** :

| Code | Appareils |
|---|---|
| `voiture` | voiture électrique, borne de recharge |
| `pac` | pompe à chaleur, chauffage électrique, climatisation |
| `ballon` | eau chaude (ballon, chauffe-eau) |
| `cuisson` | four, plaques, micro-ondes |
| `lavage` | lave-linge, sèche-linge, lave-vaisselle |
| `froid` | frigo, congélateur, cave à vin |
| `informatique` | informatique et réseau (box, ordinateur, serveur, télévision…) |
| `eclairage` | éclairage |
| `ventilation` | ventilation mécanique (VMC simple ou double flux), extracteur |
| `pompe` | pompes et traitement de l'eau : pompe de citerne, de piscine, de puits, lampe UV, adoucisseur, réservoir |
| `autre` | tout le reste |

`lavage`, `froid`, `informatique` et `eclairage` ont été ajoutés le 06/10/2026, `ventilation` et
`pompe` le 07/10/2026 (extensions compatibles : les fichiers qui ne les utilisent pas ne changent
pas ; elles valent pour les versions 1 et 2). `ventilation` et `pompe` tournent souvent en continu :
le service les compte dans la veille identifiée. Un lecteur refuse un code hors de cette liste. Un appareil mesuré à l'intérieur d'un autre (option « inclus dans » du tableau Énergie,
`included_in_stat`) porte `inclus_dans=` vers son parent ; si le parent n'est pas exporté, la mention
disparaît.

**Jamais dans le fichier** : identifiant d'entité, nom donné à l'appareil, pièce, adresse,
coordonnées, marque, coût, prix, gaz, eau.

### 3.3 Provenance de chaque ligne

| Valeur | Sens | Pas permis |
|---|---|---|
| `mesure_5min` | période de 5 min des statistiques à court terme, telle quelle | 5 |
| `mesure_15min` | quart d'heure calculé à partir des statistiques de 5 min (somme des 3 périodes) | 15 |
| `mesure_60min` | heure des statistiques à long terme | 60 ; en version 2 aussi 5 et 15 (la ligne dure une heure) |
| `heure_repartie` | heure des statistiques à long terme **répartie en parts égales** : 4 au pas de 15 min, **12** au pas de 5 min ; ce n'est **pas** une mesure au pas fin | 5, 15 (version 1 seulement) |
| `trou` | aucune donnée ; toutes les cellules sont vides ; dure le pas du fichier | 5, 15, 60 |
| `trou_60min` | version 2 : heure entière sans donnée, en une ligne ; toutes les cellules sont vides | 5, 15 (version 2 seulement) |

Dans un fichier au pas de 15 min (ou de 5 min), pour chaque heure : si au moins une période est
mesurée, les 4 (ou 12) périodes viennent des mesures (celles qui manquent sont des `trou`) ;
sinon l'heure est répartie en 4 (ou 12) parts égales, alignées sur l'heure ; une heure inconnue
donne 4 (ou 12) `trou`. Au pas de 5 min, une période connue seulement au quart d'heure n'est pas
découpée : son heure est répartie (le fichier au pas de 15 min la donne mesurée).

### 3.5 Pas de 5 minutes : compatibilité

L'extension du 06/10/2026 ajoute la valeur `5` à `pas_minutes`, la provenance `mesure_5min` et la
clé `debut_mesure_5min`. Les fichiers au pas de 15 et 60 min ne changent pas d'un octet : un
lecteur à jour lit tous les fichiers existants, et un lecteur antérieur refuse proprement un
fichier au pas de 5 min (pas inconnu) au lieu de le mal lire. La version reste donc **1**.
Le lecteur à jour applique au pas de 5 min les mêmes contrôles qu'au pas de 15 min (§ 4), avec
12 parts par heure répartie ; la tolérance du bilan d'une heure répartie tient compte des
arrondis à 4 décimales de chaque part.

### 3.6 Version 2 : le passé reste horaire (07/10/2026)

**Pourquoi.** En version 1, un fichier au pas de 5 min découpe chaque heure du passé en 12 lignes
égales qui n'apportent aucune information : un vrai export de trois ans avec plus de 20 appareils faisait
47,6 Mo, au-delà des 40 Mo du formulaire du service. La version 2 garde la même information en
≈ 12 fois moins de lignes.

**Règle.** Mêmes métadonnées, mêmes colonnes, mêmes valeurs qu'en version 1 ; seules changent
les lignes d'une heure **sans aucune mesure au pas fin** :

| Heure du passé | Version 1 (pas de 5 ou 15 min) | Version 2 |
|---|---|---|
| au moins une période mesurée au pas fin | 12 (ou 4) lignes au pas fin, `trou` pour celles qui manquent | **identique** |
| connue seulement à l'heure | 12 (ou 4) lignes `heure_repartie` égales | **une** ligne `mesure_60min` (l'heure entière) |
| inconnue | 12 (ou 4) lignes `trou` | **une** ligne `trou_60min` |

**Durée d'une ligne** : une heure pour `mesure_60min` et `trou_60min`, `pas_minutes` pour les
autres. Les lignes se suivent sans recouvrement ni vide (l'instant suivant = instant + durée) ; une
ligne horaire commence à l'heure pile, une ligne au pas fin sur un multiple du pas, et une heure
n'est jamais en partie horaire, en partie au pas fin. `fin` = début de la dernière ligne + sa durée.
`heure_repartie` n'existe pas en version 2.

**Qui produit quoi.** L'intégration (0.5.0) écrit ses **exports manuels** en version 2 aux pas de
5 et 15 min, dans un ZIP (§ 3). Au pas de 60 min, les deux versions donnent le même fichier : il
reste en **version 1**. L'**envoi direct** (API du service, par jours entiers au pas de la session)
reste en version 1. Le script `sbg_ha_export.py` (0.3.0) écrit la version 2 aux pas fins.

**Compatibilité.** Un lecteur de la version 1 refuse proprement un fichier en version 2 (version
inconnue). Un lecteur à jour lit les deux. Pour un usage au pas fin (rapport au quart d'heure),
une ligne `mesure_60min` de version 2 se répartit en 4 (ou 12) parts égales, au statut « réparti »,
exactement comme `heure_repartie` en version 1.

### 3.4 Valeurs

- Énergies **positives ou nulles**, au plus 4 décimales, sans zéros inutiles (`0.25`, `0`, `1.2346`).
- **Cellule vide = inconnu**, jamais un zéro déguisé. Une ligne `mesure_*` peut avoir des cellules
  vides (un capteur indisponible).
- Règles d'écriture (déterministes) :
  - l'énergie d'une période est la différence des `sum` de deux lignes de statistiques
    **consécutives** ; s'il manque des lignes entre deux, les périodes du trou sont inconnues —
    sauf si le cumul n'a pas bougé : elles valent alors 0 ;
  - une différence négative, ou de plus de **60 kW** de moyenne sur la période (un compteur qui
    rattrape d'un coup l'énergie d'une coupure), donne une cellule vide ;
  - la consommation n'est écrite que si tous les termes configurés sont connus ; un bilan
    négatif de moins de 10 Wh est ramené à 0, au-delà la cellule reste vide.

## 4. Ce que vérifie le lecteur

Un fichier qui ne respecte pas la structure (§ 3.1, 3.2, provenances, nombres) est **refusé**.
Sinon, contrôles du lecteur de analyse.sbg-energy.com :

1. pas régulier, sans doublon ni trou de lignes ; instants alignés sur le pas (version 2 : chaque
   ligne suit la précédente de la durée de celle-ci, lignes horaires alignées sur l'heure) ;
2. provenances permises pour le pas et la version ; lignes `trou` et `trou_60min` vides ; heures
   réparties = 4 quarts (pas de 15 min) ou 12 périodes (pas de 5 min) égaux, alignés sur l'heure ;
3. énergies positives, au plus 60 kW de moyenne sur la durée de la ligne ; colonnes non configurées vides ;
4. **bilan** de chaque ligne : `prélèvement + production − injection − charge + décharge = consommation` (à l'arrondi près) ;
5. **appareils** : somme des appareils de premier niveau ≤ consommation (tolérance 20 Wh + 5 % par
   ligne, au plus 1 % des lignes au-dessus, et sur toute la période) ; un appareil inclus ≤ son parent ;
6. signalé sans bloquer : **compteur réseau peut-être figé** (3 h de suite à exactement 0 en
   prélèvement et en injection) ;
7. au moins une ligne connue.

Verdict `valide` ou `a_verifier` ; un fichier `a_verifier` n'est jamais utilisé en silence.

## 5. Exemple synthétique (valeurs inventées)

Pas de 15 min ; deux heures du passé réparties, puis trois quarts d'heure mesurés et un trou.
Le même fichier est dans `exemple_synthetique.csv` (dépôt sbg-energy-export, dossier docs/).

```
# SBG HA export
# version: 1
# pas_minutes: 15
# fuseau: Europe/Brussels
# unite: kWh
# horodatage: debut de l'intervalle, UTC
# debut: 2026-03-10T06:00:00Z
# fin: 2026-03-10T09:00:00Z
# debut_mesure_15min: 2026-03-10T08:00:00Z
# non_configure: 
# generateur: sbg_energy_export 0.1.0
# genere_le: 2026-03-10T09:02:00Z
# appareil: voiture_1;categorie=voiture
# appareil: pac_1;categorie=pac
# appareil: autre_1;categorie=autre;inclus_dans=pac_1
debut_utc,provenance,prelevement_reseau,injection_reseau,production_solaire,charge_batterie,decharge_batterie,consommation_maison,voiture_1,pac_1,autre_1
2026-03-10T06:00:00Z,heure_repartie,0.475,0,0,0,0.1,0.575,0,0.3,0.075
2026-03-10T06:15:00Z,heure_repartie,0.475,0,0,0,0.1,0.575,0,0.3,0.075
2026-03-10T06:30:00Z,heure_repartie,0.475,0,0,0,0.1,0.575,0,0.3,0.075
2026-03-10T06:45:00Z,heure_repartie,0.475,0,0,0,0.1,0.575,0,0.3,0.075
2026-03-10T07:00:00Z,heure_repartie,0.15,0,0.075,0,0.125,0.35,0,0.2,0.05
2026-03-10T07:15:00Z,heure_repartie,0.15,0,0.075,0,0.125,0.35,0,0.2,0.05
2026-03-10T07:30:00Z,heure_repartie,0.15,0,0.075,0,0.125,0.35,0,0.2,0.05
2026-03-10T07:45:00Z,heure_repartie,0.15,0,0.075,0,0.125,0.35,0,0.2,0.05
2026-03-10T08:00:00Z,mesure_15min,0.05,0,0.12,0.02,0,0.15,0,0.1,0.03
2026-03-10T08:15:00Z,mesure_15min,0.02,0.01,0.2,0.05,0,0.16,0,0.08,0.02
2026-03-10T08:30:00Z,mesure_15min,0.6,0,0.25,0.1,0,0.75,0.55,0.05,0.01
2026-03-10T08:45:00Z,trou,,,,,,,,,
```

Lecture : à 08:30, la maison a consommé 0,75 kWh (0,6 pris au réseau + 0,25 de soleil − 0,1 mis en
batterie), dont 0,55 pour la voiture et 0,05 pour la pompe à chaleur ; `autre_1` (0,01) fait partie
de la pompe à chaleur et n'est pas compté deux fois.

Le même exemple en **version 2** : les deux heures du passé tiennent chacune en une ligne (somme
des 4 quarts), l'heure mesurée ne change pas.

```
# SBG HA export
# version: 2
# pas_minutes: 15
(mêmes métadonnées et même en-tête de colonnes que ci-dessus)
2026-03-10T06:00:00Z,mesure_60min,1.9,0,0,0,0.4,2.3,0,1.2,0.3
2026-03-10T07:00:00Z,mesure_60min,0.6,0,0.3,0,0.5,1.4,0,0.8,0.2
2026-03-10T08:00:00Z,mesure_15min,0.05,0,0.12,0.02,0,0.15,0,0.1,0.03
2026-03-10T08:15:00Z,mesure_15min,0.02,0.01,0.2,0.05,0,0.16,0,0.08,0.02
2026-03-10T08:30:00Z,mesure_15min,0.6,0,0.25,0.1,0,0.75,0.55,0.05,0.01
2026-03-10T08:45:00Z,trou,,,,,,,,,
```

## 6. Hors du format (volontairement)

- **Puissance** instantanée, état de charge de la batterie, températures : pas dans la v1.
- **Gaz et eau** : le tableau Énergie les suit, mais l'analyse électrique n'en a pas besoin.
- **Coûts** : le service les calcule à partir des contrats, pas des réglages de Home Assistant.
- **Compression dans le format** : non ; le CSV reste lisible tel quel. Il voyage dans un ZIP
  (§ 3) quand il est gros : le vrai export de trois ans au pas de 5 min (plus de 20 appareils) fait
  47,6 Mo en version 1, ≈ 5 Mo en version 2, ≈ 0,6 Mo en version 2 dans un ZIP.
- **Signature** : elle n'apporterait rien tant que l'utilisateur dépose lui-même le fichier.
