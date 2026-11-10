"""Lectores de SIMIT y Movilidad Medellín, con HTML que reproduce las páginas reales (capturas del 08/11/2026)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.scraper import parsear_medellin, parsear_simit  # noqa: E402
from core import alerts  # noqa: E402

MEDELLIN_OK = """<div><h2>Estado del vehículo</h2><label>Placa</label><input value="MOY211"><button>Buscar</button>
<table><thead><tr><th>Concepto</th><th>Estado</th></tr></thead><tbody>
<tr><td>¿Tiene pendientes judiciales?</td><td>No registra</td></tr>
<tr><td>¿Tiene prenda a favor de la entidad financiera?</td><td>Sí</td></tr>
<tr><td>¿Tiene multas asociadas al vehículo o propietario?</td><td>Sí</td></tr>
<tr><td>¿Cual(es) vigencia(s) de tasas municipales de sistematización y señalización tiene pendiente de pago?</td><td>No</td></tr>
<tr><td>Estado actual del vehículo</td><td>Activo</td></tr>
<tr><td>¿Se encuentra inmovilizado?</td><td>No <a>Descargar Certificado</a></td></tr>
</tbody></table></div>"""

MEDELLIN_NO_MATRICULADO = """<div class="toast">El vehículo no se encuentra matriculado en la Secretaría de Movilidad
del Distrito Especial de Ciencia, Tecnología e Innovación de Medellín.</div><label>Placa</label><input value="EGX799">"""

MEDELLIN_SIN_RESULTADO = """<h2>Estado del vehículo</h2><p>En esta opción encontrará información relacionada con el estado
del vehículo a consultar: pagos pendientes con el Municipio, prendas a favor de entidad financiera, pendientes judiciales,
inmovilizaciones y multas asociadas al vehículo o propietario.</p><span>Placa</span><input placeholder="Ingrese una placa"
value="GOB107"><button>Buscar</button>"""

SIMIT_MULTA = """<h1>Estado de cuenta</h1><div>Resumen</div><div>Comparendos: <b>0</b></div><div>Multas: <b>1</b></div>
<div>Acuerdos de pago: <b>0</b></div><div>Total: <b>$ 721.470</b></div><h3>Comparendos y Multas</h3>
<table><thead><tr><th>Tipo</th><th>Notificación</th><th>Placa</th><th>Secretaría</th><th>Infracción</th><th>Estado</th>
<th>Valor</th><th>Valor a pagar</th><th></th></tr></thead><tbody>
<tr><td><a>0000618596</a> Multa Fecha coactivo: 11/07/2023</td><td>No aplica</td><td>MOY211</td><td>Medellin</td>
<td>C29... Fotodetección</td><td>Cobro coactivo</td><td>$ 522.940 Interés $ 198.530</td><td>$ 721.470 Detalle Pago</td><td></td></tr>
</tbody></table><div>Total (1): $ 721.470</div>"""

SIMIT_LIMPIO = """<h1>Estado de cuenta</h1><h2>No tienes comparendos ni multas registradas en Simit</h2>
<p>Revisa con tu número de identificación y/o placa en las Secretarías de Tránsito...</p>"""


def test_medellin():
    r = parsear_medellin(MEDELLIN_OK)
    assert [d["Estado"][:2] for d in r["detalle"]] == ["No", "Sí", "Sí", "No", "Ac", "No"], r["detalle"]
    assert len(r["multas"]) == 1 and not r["reportes"] and r["informativo"]
    r3 = parsear_medellin(MEDELLIN_SIN_RESULTADO)   # caso real del 08/11: sin tabla -> sin alertas falsas
    assert r3.get("error_lectura") and not r3["multas"] and not r3["reportes"], r3
    r2 = parsear_medellin(MEDELLIN_NO_MATRICULADO)
    assert r2.get("no_matriculado") and not r2["multas"]


def test_simit():
    r = parsear_simit(SIMIT_MULTA)
    assert r["resumen"] == {"comparendos": 0, "multas": 1, "acuerdos": 0, "total": 721470.0}, r["resumen"]
    assert len(r["multas"]) == 1 and r["multas"][0]["valor"] == 721470.0 and r["multas"][0]["estado"] == "Pendiente"
    assert "Cobro coactivo" in r["multas"][0]["descripcion"]
    r2 = parsear_simit(SIMIT_LIMPIO)
    assert r2["sin_novedad"] and not r2["multas"]


def test_alerta():
    local = {"vehiculo": None, "documentos": [], "multas": [], "reportes": []}
    a = alerts.evaluar("MOY211", None, local, {"SIMIT": parsear_simit(SIMIT_MULTA),
                                                 "Movilidad Medellín": parsear_medellin(MEDELLIN_OK)})
    assert a["categoria"] == "MULTAS_DEUDA", a["categoria"]
    b = alerts.evaluar("EGX799", None, local, {"SIMIT": parsear_simit(SIMIT_LIMPIO),
                                                 "Movilidad Medellín": parsear_medellin(MEDELLIN_NO_MATRICULADO)})
    assert b["categoria"] == "NORMAL"


if __name__ == "__main__":
    test_medellin(); test_simit(); test_alerta()
    print("lectores de portales OK")
