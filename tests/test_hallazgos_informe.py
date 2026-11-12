"""Regresión de los hallazgos del «Informe de pruebas — PlateGuardAI» (12/11/2026).

H1. «Sin alertas» y «sin información» se veían igual (pantalla verde para una placa no consultada).
H2. Una lectura incompleta se reconstruía como placa válida (MG650 -> MGG50).
R3. La confianza del OCR no se usaba: lecturas dudosas daban resultado sin confirmación.
R4. test_cola.py usaba la base real (se verifica que ahora es temporal).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'hallazgos.db'}"

import cv2  # noqa: E402

from core import alerts, database as db, ocr, pipeline  # noqa: E402

VACIO = {"vehiculo": None, "documentos": [], "multas": [], "reportes": []}
RAIZ = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- H1
def test_h1_no_registrado_no_es_sin_alertas():
    db.inicializar()
    for placa in ("MGG50", "OMG650"):
        r = alerts.evaluar(placa, None, VACIO)
        assert r["categoria"] == "SIN_REGISTRO", (placa, r["categoria"])
        assert "Continuar" not in r["info"]["protocolo"]
        assert r["verificado_en"] == []
    limpio = alerts.evaluar("LUZ482", None, db.registro_completo("LUZ482"))
    assert limpio["categoria"] == "NORMAL" and limpio["verificado_en"] == ["Base de datos del sistema"]
    # las tres situaciones del informe ya NO producen la misma pantalla
    assert alerts.evaluar("MGG50", None, VACIO)["info"]["titulo"] != limpio["info"]["titulo"]


def test_h1_que_cuenta_como_verificacion():
    simit_limpio = {"sin_novedad": True, "multas": [], "reportes": [], "documentos": []}
    no_matriculado = {"no_matriculado": True, "multas": [], "reportes": [], "documentos": []}
    ilegible = {"error_lectura": True, "multas": [], "reportes": [], "documentos": []}
    assert alerts.evaluar("OMG650", None, VACIO, {"SIMIT": simit_limpio})["categoria"] == "NORMAL"
    assert alerts.evaluar("OMG650", None, VACIO, {"Movilidad Medellín": no_matriculado})["categoria"] == "SIN_REGISTRO"
    assert alerts.evaluar("OMG650", None, VACIO, {"SIMIT": ilegible})["categoria"] == "SIN_REGISTRO"
    # una multa en línea sigue alertando aunque la placa no esté en la base
    con_multa = {"multas": [{"descripcion": "C13", "estado": "Pendiente"}], "reportes": [], "documentos": []}
    assert alerts.evaluar("OMG650", None, VACIO, {"SIMIT": con_multa})["categoria"] == "MULTAS_DEUDA"


def test_h1_prioridad_sin_registro_no_tapa_alertas():
    db.inicializar()
    assert alerts.evaluar("MNB654", None, db.registro_completo("MNB654"))["categoria"] == "ACTO_ILEGAL"


# ---------------------------------------------------------------- H2
def test_h2_no_reconstruye_lecturas_incompletas():
    assert ocr.corregir_formato_colombiano("MG650") == "MG650"          # antes: MGG50
    c = ocr.evaluar_lectura("MG650", "MG650", 0.92)
    assert c["requiere_confirmacion"] and "incompleta" in c["motivos"][0].lower()


def test_h2_sigue_corrigiendo_lo_razonable():
    assert ocr.corregir_formato_colombiano("IGNP75F") == "GNP75F"       # borde de la placa
    assert ocr.corregir_formato_colombiano("GNPT5F") == "GNP75F"        # T->7, una corrección
    assert not ocr.evaluar_lectura("GNPT5F", "GNP75F", 0.9)["requiere_confirmacion"]
    assert ocr.corregir_formato_colombiano("PCD7841") == "PCD7841"      # extranjera completa


def test_h2_cinco_caracteres_pide_confirmacion():
    assert ocr.evaluar_lectura("ABC12", "ABC12", 0.95)["requiere_confirmacion"]


def test_h2_sugerencia_con_caracter_faltante():
    db.inicializar()
    db.guardar_vehiculo(dict(placa="OMG650", naturaleza="nacional", tipo="carro", servicio="Particular",
                             marca="x", linea="x", modelo=2010, color="x", ciudad="x"))
    assert "OMG650" in db.placas_similares("MG650")                     # falta la O inicial
    assert "HJK321" in db.placas_similares("HIK321")                    # J leída como I


# ---------------------------------------------------------------- R3
def test_r3_confianza_baja_pide_confirmacion():
    assert ocr.evaluar_lectura("KTM123", "KTM123", 0.30)["requiere_confirmacion"]
    assert not ocr.evaluar_lectura("KTM123", "KTM123", 0.90)["requiere_confirmacion"]


def test_r3_pipeline_no_da_resultado_sin_confirmacion():
    """Caso de campo: el OCR entrega MG650 con 92 % -> no hay alerta, hay pedido de confirmación."""
    db.inicializar()
    img = cv2.imread(str(RAIZ / "data" / "demo" / "demo_LUZ482.jpg"))
    original = ocr.leer_placa
    try:
        def lectura_incompleta(recorte, corregir=True):
            r = original(recorte, corregir)
            r.update(texto="MG650", texto_bruto="MG650", confianza=0.92, correcciones=0)
            return r
        ocr.leer_placa = lectura_incompleta
        r = pipeline.procesar_imagen(img)
    finally:
        ocr.leer_placa = original
    assert r["requiere_confirmacion"] and r["alerta"] is None
    assert "OMG650" in r["sugerencias"] or db.placas_similares("MG650") == []
    # con la placa confirmada por el agente sí hay resultado
    r2 = pipeline.procesar_imagen(img, placa_manual="LUZ482")
    assert not r2["requiere_confirmacion"] and r2["alerta"]["categoria"] == "NORMAL"


# ---------------------------------------------------------------- R4
def test_r4_test_cola_usa_base_temporal():
    fuente = (RAIZ / "tests" / "test_cola.py").read_text(encoding="utf-8")
    pos_env = fuente.index('os.environ["DATABASE_URL"]')
    pos_import = fuente.index("from core import database")
    assert pos_env < pos_import


if __name__ == "__main__":
    pruebas = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in pruebas:
        t()
    print(f"hallazgos del informe: {len(pruebas)} pruebas OK")
