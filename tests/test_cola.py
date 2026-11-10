"""Prueba del circuito web -> cola -> nodo -> base de datos -> web, sin red.
El scraping real se reemplaza por HTML de ejemplo."""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import database as db, scraper  # noqa: E402
from tests.test_portales import SIMIT_MULTA as HTML  # noqa: E402

import nodo_scraping  # noqa: E402


def falso_scraping(placa, fuente, visible=True, espera_resultado_seg=25):
    datos = scraper.parsear_resultado(HTML, fuente)
    db.cache_set(placa, fuente, datos)
    return scraper.ResultadoScraping(True, datos, "Consulta en línea completada (simulada)")


def test_cola():
    db.inicializar()
    with db.conexion() as con:
        db._q(con, "DELETE FROM cache_scraping WHERE placa='TST999'")
        db._q(con, "DELETE FROM solicitudes WHERE placa='TST999'")
    # 1) La "web" (sin Playwright) pide una consulta
    scraper.puede_scrapear_aqui = lambda: False
    r = scraper.consultar_fuente("TST999", "simit")
    assert r.pendiente and not r.datos, r
    assert db.estado_solicitud("TST999", "simit")["estado"] == "pendiente"
    # 2) El nodo atiende la cola
    scraper.ejecutar_scraping = falso_scraping
    nodo_scraping.INTERVALO = 0.5
    threading.Thread(target=nodo_scraping.nodo_continuo, args=(["simit"], False, 120), daemon=True).start()
    for _ in range(20):
        time.sleep(0.5)
        if db.estado_solicitud("TST999", "simit")["estado"] == "completada":
            break
    assert db.estado_solicitud("TST999", "simit")["estado"] == "completada"
    assert any(n["en_linea"] for n in db.estado_nodos())
    # 3) La web vuelve a consultar y obtiene el resultado guardado
    r2 = scraper.consultar_fuente("TST999", "simit")
    assert r2.ok and r2.desde_cache and len(r2.datos["multas"]) == 1, r2


if __name__ == "__main__":
    test_cola()
    print("cola OK con", db.descripcion_motor())
