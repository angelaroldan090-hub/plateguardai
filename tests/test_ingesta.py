"""Ingesta continua: el nodo refresca las placas en seguimiento y registra cada ciclo (sin red)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.mkdtemp()) / 'ingesta.db'}")
from core import database as db, scraper  # noqa: E402
from tests.test_portales import SIMIT_MULTA, MEDELLIN_OK  # noqa: E402
import nodo_scraping  # noqa: E402

consultas = []


def falso(placa, fuente, visible=True, espera_resultado_seg=25):
    consultas.append((placa, fuente))
    datos = scraper.parsear_resultado(SIMIT_MULTA if fuente == "simit" else MEDELLIN_OK, fuente)
    db.cache_set(placa, fuente, datos)
    return scraper.ResultadoScraping(True, datos, "ok (simulado)")


def test_ingesta():
    db.inicializar()
    scraper.ejecutar_scraping = falso
    nodo_scraping.time.sleep = lambda s: None
    db.agregar_seguimiento("TST001", "simit,medellin", "prueba")
    db.agregar_seguimiento("TST002", "simit", "prueba")
    assert len(db.pendientes_de_ingesta(2)) == 3
    from datetime import datetime
    ok, err = nodo_scraping.ciclo_ingesta(["simit", "medellin"], False, 2, datetime.now())
    assert (ok, err) == (3, 0) and len(consultas) == 3
    assert db.pendientes_de_ingesta(2) == []                 # todo al día
    ing = db.ultimas_ingestas(1)
    assert ing.iloc[0]["estado"] == "completada" and ing.iloc[0]["consultas_ok"] == 3
    # un segundo ciclo inmediato no repite consultas
    nodo_scraping.ciclo_ingesta(["simit", "medellin"], False, 2, datetime.now())
    assert len(consultas) == 3
    # con vigencia 0 h todo vuelve a quedar pendiente (simula que pasaron 2 horas)
    assert len(db.pendientes_de_ingesta(0)) == 3
    db.quitar_seguimiento("TST002")
    assert len(db.lista_seguimiento()) == 1


if __name__ == "__main__":
    test_ingesta()
    print("ingesta continua OK con", db.descripcion_motor())
