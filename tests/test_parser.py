"""Prueba del parser de scraping con HTML de ejemplo (sin red)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.scraper import _parsear_generico as parsear_resultado

HTML = """<html><body><h3>Resultado de la consulta</h3>
<table><tr><th>Tipo</th><th>Detalle</th><th>Valor</th><th>Estado</th></tr>
<tr><td>Comparendo</td><td>C29 Exceso de velocidad 2026-05-02</td><td>$ 604.200</td><td>Pendiente</td></tr>
<tr><td>Multa</td><td>D12 Inmovilización por no portar licencia</td><td>$ 1.208.400</td><td>Pendiente</td></tr>
<tr><td>SOAT</td><td>Póliza vencida 2026-09-30</td><td></td><td>No vigente</td></tr>
<tr><td>Revisión técnico mecánica</td><td>Vigente hasta 2027-03-01</td><td></td><td>Vigente</td></tr>
</table></body></html>"""

HTML_OK = "<html><body><div class='alert'>El vehículo no tiene comparendos ni multas registradas.</div></body></html>"

def test_parser():
    r = parsear_resultado(HTML, "simit")
    assert len(r["multas"]) == 2 and r["multas"][0]["valor"] == 604200
    assert r["multas"][1]["inmoviliza"] == 1
    assert any(d["vencido"] for d in r["documentos"]) and len(r["documentos"]) == 2
    r2 = parsear_resultado(HTML_OK, "runt")
    assert r2["sin_novedad"] and not r2["multas"]

if __name__ == "__main__":
    test_parser(); print("parser OK")
