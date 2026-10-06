# SPDX-License-Identifier: Apache-2.0
"""Stockage local : fichiers mensuels, ajout, fusion, compression, conservation (sans Home Assistant)."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip

import pytest

from custom_components.sbg_energy_export import stockage as S

UTC = timezone.utc
T0 = int(datetime(2026, 1, 31, 23, 0, tzinfo=UTC).timestamp())  # dernière heure de janvier
Q = 900


def test_ajout_simple_puis_nouvelle_colonne(tmp_path):
    S.enregistrer(tmp_path, 15, {"sensor.a": {T0: 0.25, T0 + Q: 0.5}, "sensor.b": {T0: 1.0}})
    f = tmp_path / "mesures_15min_2026-01.csv"
    assert f.read_text(encoding="utf-8") == (
        "debut_utc,sensor.a,sensor.b\n"
        "2026-01-31T23:00:00Z,0.25,1\n"
        "2026-01-31T23:15:00Z,0.5,\n")
    # suite du fichier, mêmes colonnes : simple ajout
    S.enregistrer(tmp_path, 15, {"sensor.a": {T0 + 2 * Q: 0.0}})
    assert f.read_text(encoding="utf-8").endswith("2026-01-31T23:30:00Z,0,\n")
    # nouvelle statistique : le mois est réécrit avec une colonne de plus
    S.enregistrer(tmp_path, 15, {"sensor.c": {T0: 0.1234567}})
    lignes = f.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "debut_utc,sensor.a,sensor.b,sensor.c"
    assert lignes[1] == "2026-01-31T23:00:00Z,0.25,1,0.123457"
    assert len(lignes) == 4


def test_mois_suivant_compression_et_lecture_transparente(tmp_path):
    S.enregistrer(tmp_path, 15, {"sensor.a": {T0 + k * Q: 0.1 * k for k in range(8)}})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mesures_15min_2026-01.csv", "mesures_15min_2026-02.csv"]
    assert S.entretenir(tmp_path, "2026-02", "2023-02") == (1, 0)
    gz = tmp_path / "mesures_15min_2026-01.csv.gz"
    assert sorted(p.name for p in tmp_path.iterdir()) == [gz.name, "mesures_15min_2026-02.csv"]
    assert gzip.decompress(gz.read_bytes()).decode().startswith("debut_utc,sensor.a\n2026-01-31T23:00:00Z,0\n")
    assert gz.read_bytes()[4:8] == b"\0\0\0\0"  # pas de date dans l'en-tête gzip : compression reproductible
    lu = S.lire(tmp_path, 15, ["sensor.a", "sensor.x"], T0, T0 + 8 * Q)
    assert lu["sensor.a"] == {T0 + k * Q: pytest.approx(0.1 * k) for k in range(8)}
    assert lu["sensor.x"] == {}
    assert S.lire(tmp_path, 5, ["sensor.a"], T0, T0 + 8 * Q) == {"sensor.a": {}}
    # rattrapage dans un mois déjà compressé : fusion dans le .gz
    S.enregistrer(tmp_path, 15, {"sensor.b": {T0: 2.0}})
    assert not (tmp_path / "mesures_15min_2026-01.csv").exists()
    colonnes, lignes = S.lire_fichier(gz)
    assert colonnes == ["sensor.a", "sensor.b"] and lignes[T0] == {"sensor.a": 0.0, "sensor.b": 2.0}


def test_conservation(tmp_path):
    for mois in ("2022-12", "2023-01", "2026-01"):
        t = int(datetime.fromisoformat(mois + "-15T00:00:00+00:00").timestamp())
        S.enregistrer(tmp_path, 5, {"sensor.a": {t: 0.01}})
    maintenant = int(datetime(2026, 1, 20, tzinfo=UTC).timestamp())
    assert S.mois_limite(maintenant, 3) == "2023-01"
    assert S.entretenir(tmp_path, "2026-01", S.mois_limite(maintenant, 3)) == (1, 1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mesures_5min_2023-01.csv.gz", "mesures_5min_2026-01.csv"]


def test_fichier_illisible_ignore(tmp_path):
    (tmp_path / "mesures_15min_2026-01.csv.gz").write_bytes(b"pas du gzip")
    assert S.lire(tmp_path, 15, ["sensor.a"], T0, T0 + Q) == {"sensor.a": {}}


def test_migration_version_0_1(tmp_path):
    ancien = tmp_path / "quarts"
    ancien.mkdir()
    (ancien / "quarts_2026-01.csv").write_text(
        "debut_utc,statistique,kwh\n"
        "2026-01-31T23:00:00Z,sensor.import,0.250000\n"
        "2026-01-31T23:00:00Z,sensor.appareil_non_choisi,1.000000\n", encoding="utf-8")
    assert S.migrer_ancien(ancien, tmp_path / "mesures", {"sensor.import"}) == 1
    assert not ancien.exists()
    assert S.lire(tmp_path / "mesures", 15, ["sensor.import", "sensor.appareil_non_choisi"], T0, T0 + Q) == {
        "sensor.import": {T0: 0.25}, "sensor.appareil_non_choisi": {}}
