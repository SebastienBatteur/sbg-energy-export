"""Script manuel ``outils/sbg_ha_export.py`` : copie du code partagé, modes hors ligne, client WebSocket."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import sys
import threading

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "outils"))
import assembler_script  # noqa: E402


def charger_script():
    spec = importlib.util.spec_from_file_location("sbg_ha_export", RACINE / "outils" / "sbg_ha_export.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # nécessaire aux dataclasses
    spec.loader.exec_module(module)
    return module


def test_script_a_jour():
    """Le script distribué = assemblage actuel (lancer outils/assembler_script.py)."""
    assert (RACINE / "outils" / "sbg_ha_export.py").read_text(encoding="utf-8") == assembler_script.assembler()


def test_depuis_json(tmp_path):
    s = charger_script()
    t0 = 1767607200  # 2026-01-05T10:00Z
    stats = {
        "sensor.import": [{"start": (t0 + k * 3600) * 1000, "sum": 10.0 + k} for k in range(4)],
        "sensor.export": [{"start": (t0 + k * 3600) * 1000, "sum": 5.0} for k in range(4)],
        "sensor.borne": [{"start": (t0 + k * 3600) * 1000, "sum": 2.0 + 0.5 * k} for k in range(4)],
    }
    src = tmp_path / "stats.json"
    src.write_text(json.dumps(stats), encoding="utf-8")
    sortie = tmp_path / "x.csv"
    assert s.principal(["--depuis-json", str(src), "--role", "prelevement=sensor.import", "--role",
                        "injection=sensor.export", "--appareil", "sensor.borne=voiture", "--sortie", str(sortie)]) == 0
    texte = sortie.read_text(encoding="utf-8")
    corps = [l for l in texte.splitlines() if not l.startswith("#")]
    assert corps[0].endswith("consommation_maison,voiture_1")
    assert corps[1] == "2026-01-05T11:00:00Z,mesure_60min,1,0,,,,1,0.5"
    assert len(corps) == 4  # 11 h, 12 h, 13 h
    assert "sensor" not in texte


def test_depuis_csv_du_tableau_energie(tmp_path):
    s = charger_script()
    f = tmp_path / "energy.csv"
    f.write_text(
        "entity_id,type,unit,2026-01-05T10:00:00.000Z,2026-01-05T11:00:00.000Z,2026-01-05T12:00:00.000Z\n"
        "sensor.import,grid_consumption,kWh,1.5,0.5,\n"
        "sensor.import_cost,grid_consumption_cost,EUR,0.4,0.1,\n"
        "sensor.pv,solar_production,kWh,0,2,1\n"
        "sensor.export,grid_return,kWh,0,1,0.5\n"
        "sensor.borne,device_consumption,kWh,1,0,0\n"
        ",calculated_total_consumption,kWh,1.5,1.5,\n",
        encoding="utf-8")
    sortie = tmp_path / "x.csv"
    assert s.principal(["--depuis-csv", str(f), "--appareil", "sensor.borne=voiture", "--sortie", str(sortie)]) == 0
    corps = [l for l in sortie.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    assert corps[1:] == [
        "2026-01-05T10:00:00Z,mesure_60min,1.5,0,0,,,1.5,1",
        "2026-01-05T11:00:00Z,mesure_60min,0.5,1,2,,,1.5,0",
        "2026-01-05T12:00:00Z,mesure_60min,,0.5,1,,,,0",
    ]


def test_csv_non_horaire_refuse(tmp_path):
    s = charger_script()
    f = tmp_path / "energy.csv"
    f.write_text("entity_id,type,unit,2026-01-05T00:00:00.000Z,2026-01-06T00:00:00.000Z\n"
                 "sensor.import,grid_consumption,kWh,10,12\n", encoding="utf-8")
    with pytest.raises(ValueError, match="3 jours"):
        s.lire_csv_energie([str(f)])


# ------------------------------------------------------------ faux Home Assistant local
def _trame_serveur(donnees: bytes) -> bytes:
    n = len(donnees)
    if n < 126:
        return struct.pack("!BB", 0x81, n) + donnees
    if n < 65536:
        return struct.pack("!BBH", 0x81, 126, n) + donnees
    return struct.pack("!BBQ", 0x81, 127, n) + donnees


def _lire_trame(conn) -> dict:
    def lire(n):
        d = b""
        while len(d) < n:
            d += conn.recv(n - len(d))
        return d
    b1, b2 = lire(2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", lire(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", lire(8))[0]
    masque = lire(4)
    return json.loads(bytes(b ^ masque[i % 4] for i, b in enumerate(lire(n))))


def faux_home_assistant(serveur: socket.socket, recu: list) -> None:
    conn, _ = serveur.accept()
    requete = b""
    while b"\r\n\r\n" not in requete:
        requete += conn.recv(4096)
    cle = [l.split(b": ")[1] for l in requete.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
    accept = base64.b64encode(hashlib.sha1(cle + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
    conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                 b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
    conn.sendall(_trame_serveur(json.dumps({"type": "auth_required"}).encode()))
    recu.append(_lire_trame(conn))
    conn.sendall(_trame_serveur(json.dumps({"type": "auth_ok"}).encode()))
    m = _lire_trame(conn)
    recu.append(m)
    gros = {"sensor.x": [{"start": k * 3600000, "sum": float(k)} for k in range(3000)]}  # > 64 kio
    conn.sendall(_trame_serveur(json.dumps({"id": m["id"], "type": "result", "success": True,
                                            "result": gros}).encode()))
    conn.close()


def test_client_websocket_local(socket_enabled):  # serveur local 127.0.0.1 seulement
    s = charger_script()
    serveur = socket.socket()
    serveur.bind(("127.0.0.1", 0))
    serveur.listen(1)
    recu: list = []
    fil = threading.Thread(target=faux_home_assistant, args=(serveur, recu), daemon=True)
    fil.start()
    ws = s.connecter(f"http://127.0.0.1:{serveur.getsockname()[1]}", "jeton-de-test", True)
    r = ws.commande({"type": "recorder/statistics_during_period", "statistic_ids": ["sensor.x"]})
    fil.join(5)
    serveur.close()
    assert recu[0] == {"type": "auth", "access_token": "jeton-de-test"}
    assert recu[1]["type"] == "recorder/statistics_during_period"
    assert len(r["sensor.x"]) == 3000
