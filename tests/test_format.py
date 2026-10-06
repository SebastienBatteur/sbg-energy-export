"""Format « SBG HA export » : construction et écriture (sans Home Assistant)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.sbg_energy_export import sbg_format as F

H = 3600
T0 = int(datetime(2026, 1, 5, 10, tzinfo=timezone.utc).timestamp())


def cumuls(debut: int, pas: int, energies: list[float | None]) -> list[dict]:
    """Lignes de statistiques (``sum`` cumulé) ; None = ligne absente."""
    lignes, s = [{"start": debut - pas, "sum": 100.0}], 100.0
    for k, e in enumerate(energies):
        if e is None:
            continue
        s += e
        lignes.append({"start": debut + k * pas, "sum": s})
    return lignes


PREFS = {
    "energy_sources": [
        {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.hp"}, {"stat_energy_from": "sensor.hc"}],
         "flow_to": [{"stat_energy_to": "sensor.inj"}], "cost_adjustment_day": 0},
        {"type": "solar", "stat_energy_from": "sensor.pv", "config_entry_solar_forecast": None},
        {"type": "gas", "stat_energy_from": "sensor.gaz"},
    ],
    "device_consumption": [
        {"stat_consumption": "sensor.borne_garage"},
        {"stat_consumption": "sensor.pac_salon"},
        {"stat_consumption": "sensor.compresseur", "included_in_stat": "sensor.pac_salon"},
        {"stat_consumption": "sensor.lave_linge"},
    ],
}


def test_variations_contigues_trous_et_rattrapages():
    lignes = cumuls(T0, H, [1.0, 2.0, None, 0.5, 70.0, 0.25])
    v = F.variations(lignes, H)
    assert v[T0] == 1.0 and v[T0 + H] == 2.0
    assert T0 + 2 * H not in v and T0 + 3 * H not in v  # trou puis énergie : inconnu
    assert T0 + 4 * H not in v                             # 70 kWh en 1 h : rattrapage
    assert v[T0 + 5 * H] == 0.25


def test_variations_trou_sans_energie_vaut_zero():
    lignes = cumuls(T0, H, [1.0, None, None, 0.0, 2.0])
    v = F.variations(lignes, H)
    assert [v.get(T0 + k * H) for k in range(5)] == [1.0, 0.0, 0.0, 0.0, 2.0]


def test_variations_negative_et_instants_en_millisecondes():
    lignes = [{"start": T0 * 1000, "sum": 5.0}, {"start": (T0 + H) * 1000, "sum": 4.0},
              {"start": (T0 + 2 * H) * 1000, "sum": 4.5}]
    assert F.variations(lignes, H) == {T0 + 2 * H: 0.5}


def test_regrouper_exige_trois_periodes():
    v = {T0: 0.1, T0 + 300: 0.2, T0 + 600: 0.3, T0 + 900: 0.1, T0 + 1200: 0.1}
    q = F.regrouper(v, 300, 900)
    assert q == {T0: pytest.approx(0.6)}


def test_preferences_ancien_et_nouveau_format_reseau():
    c = F.depuis_preferences(PREFS, [], {})
    assert c.roles == {F.PRELEVEMENT: ["sensor.hp", "sensor.hc"], F.INJECTION: ["sensor.inj"], F.SOLAIRE: ["sensor.pv"]}
    assert c.non_configures() == [F.CHARGE, F.DECHARGE]
    unifie = {"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.a", "stat_energy_to": "sensor.b"},
        {"type": "battery", "stat_energy_from": "sensor.dech", "stat_energy_to": "sensor.ch"}]}
    c = F.depuis_preferences(unifie, [], {})
    assert c.roles == {F.PRELEVEMENT: ["sensor.a"], F.INJECTION: ["sensor.b"], F.CHARGE: ["sensor.ch"],
                       F.DECHARGE: ["sensor.dech"]}


def test_noms_neutres_et_appareil_inclus():
    tous = [d["stat_consumption"] for d in PREFS["device_consumption"]]
    cats = {"sensor.borne_garage": "voiture", "sensor.pac_salon": "pac", "sensor.compresseur": "autre"}
    cols = F.depuis_preferences(PREFS, tous, cats).colonnes()
    assert [(c.nom, c.categorie, c.inclus_dans) for c in cols] == [
        ("voiture_1", "voiture", None), ("pac_1", "pac", None), ("autre_1", "autre", "pac_1"), ("autre_2", "autre", None)]
    # parent non retenu : l'appareil inclus redevient indépendant
    cols = F.depuis_preferences(PREFS, ["sensor.compresseur"], cats).colonnes()
    assert [(c.nom, c.inclus_dans) for c in cols] == [("autre_1", None)]
    with pytest.raises(ValueError):
        F.Configuration({}, [F.Appareil("sensor.x", "frigo")]).colonnes()


def test_lignes_bilan_et_non_configures():
    c = F.Configuration({F.PRELEVEMENT: ["p"], F.INJECTION: ["i"], F.SOLAIRE: ["s"]}, [F.Appareil("v", "voiture")])
    e = {"p": {T0: 1.0, T0 + H: 0.0}, "i": {T0: 0.5, T0 + H: 2.0}, "s": {T0: 2.0, T0 + H: 1.0}, "v": {T0: 1.5}}
    l = F.construire_lignes(c, e, T0, T0 + 3 * H, H, F.MESURE_60)
    assert l[0].valeurs[F.CONSO] == pytest.approx(2.5)
    assert l[0].valeurs[F.CHARGE] is None  # non configuré : vide, pas zéro
    assert l[1].valeurs[F.CONSO] is None   # bilan négatif (-1 kWh) : inconnu
    assert l[1].provenance == F.MESURE_60
    assert l[2].provenance == F.TROU


def test_assembler_quarts():
    c = F.Configuration({F.PRELEVEMENT: ["p"]})
    heures = F.construire_lignes(c, {"p": {T0: 2.0, T0 + H: 4.0}}, T0, T0 + 3 * H, H, F.MESURE_60)
    q = F.construire_lignes(c, {"p": {T0 + H: 1.0, T0 + H + 900: 1.5}}, T0 + H, T0 + 2 * H, 900, F.MESURE_15)
    l = F.assembler_quarts(heures, {x.debut: x for x in q if x.provenance != F.TROU})
    assert [x.provenance for x in l] == [F.HEURE_REPARTIE] * 4 + [F.MESURE_15] * 2 + [F.TROU] * 2 + [F.TROU] * 4
    assert l[0].valeurs[F.PRELEVEMENT] == 0.5
    assert [x.debut for x in l] == [T0 + 900 * k for k in range(12)]


def test_exporter_texte_complet_sans_identifiant():
    prefs = {"energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.compteur_rue_x", "stat_energy_to": "sensor.inj"}],
        "device_consumption": [{"stat_consumption": "sensor.borne_garage"}]}
    c = F.depuis_preferences(prefs, ["sensor.borne_garage"], {"sensor.borne_garage": "voiture"})
    horaires = {"sensor.compteur_rue_x": cumuls(T0, H, [1.2, 0.4]), "sensor.inj": cumuls(T0, H, [0.0, 0.1]),
                "sensor.borne_garage": cumuls(T0, H, [1.0, 0.0])}
    quarts = {"sensor.compteur_rue_x": {T0 + H + 900 * k: 0.1 for k in range(4)},
              "sensor.inj": {T0 + H + 900 * k: 0.025 for k in range(4)},
              "sensor.borne_garage": {T0 + H + 900 * k: 0.0 for k in range(4)}}
    texte = F.exporter(c, horaires, T0, T0 + 2 * H, 15, "Europe/Brussels", "test 0", T0 + 3 * H, quarts)
    assert texte == """\
# SBG HA export
# version: 1
# pas_minutes: 15
# fuseau: Europe/Brussels
# unite: kWh
# horodatage: debut de l'intervalle, UTC
# debut: 2026-01-05T10:00:00Z
# fin: 2026-01-05T12:00:00Z
# debut_mesure_15min: 2026-01-05T11:00:00Z
# non_configure: production_solaire,charge_batterie,decharge_batterie
# generateur: test 0
# genere_le: 2026-01-05T13:00:00Z
# appareil: voiture_1;categorie=voiture
debut_utc,provenance,prelevement_reseau,injection_reseau,production_solaire,charge_batterie,decharge_batterie,consommation_maison,voiture_1
2026-01-05T10:00:00Z,heure_repartie,0.3,0,,,,0.3,0.25
2026-01-05T10:15:00Z,heure_repartie,0.3,0,,,,0.3,0.25
2026-01-05T10:30:00Z,heure_repartie,0.3,0,,,,0.3,0.25
2026-01-05T10:45:00Z,heure_repartie,0.3,0,,,,0.3,0.25
2026-01-05T11:00:00Z,mesure_15min,0.1,0.025,,,,0.075,0
2026-01-05T11:15:00Z,mesure_15min,0.1,0.025,,,,0.075,0
2026-01-05T11:30:00Z,mesure_15min,0.1,0.025,,,,0.075,0
2026-01-05T11:45:00Z,mesure_15min,0.1,0.025,,,,0.075,0
"""
    assert "sensor." not in texte and "garage" not in texte and "rue" not in texte


def test_nombre():
    assert F.nombre(None) == "" and F.nombre(0.0) == "0" and F.nombre(-0.00001) == "0"
    assert F.nombre(1.23456) == "1.2346" and F.nombre(2.5) == "2.5"


def test_pas_refuse():
    with pytest.raises(ValueError):
        F.ecrire(F.Configuration(), [], 30, "UTC", "x", T0)
