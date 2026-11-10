"""Prueba de extremo a extremo del cruce de registros y el sistema de alertas con FOTOS REALES.

Toma imágenes reales, deja que el sistema detecte y lea la placa, y la cruza con una base de
datos de PRUEBA (temporal, nunca la de la nube) en la que a cada placa leída se le asigna un
escenario: sin alertas, deuda/multas/delitos, documentos vencidos, reportado en acto ilegal.

Uso:
    python tools/prueba_alertas.py img1.jpg img2.jpg img3.jpg img4.jpg [img5.jpg]
Salida: data/pruebas/reporte_alertas.html con cada imagen anotada y su alerta.

Los registros asignados son ficticios y solo existen durante la prueba (Ley 1581 de 2012).
"""
import base64
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
_tmp = Path(tempfile.mkdtemp()) / "prueba_alertas.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"   # base temporal, aislada de la real

import cv2  # noqa: E402

from core import database as db, pipeline  # noqa: E402
from core.config import CATEGORIAS_ALERTA  # noqa: E402

ESCENARIOS = [
    ("NORMAL", "Sin alertas: Normal"),
    ("MULTAS_DEUDA", "Deuda, multas o delitos: Alerta"),
    ("DOCUMENTOS_VENCIDOS", "Documentos vencidos: Alerta"),
    ("ACTO_ILEGAL", "Vehículo reportado en acto ilegal: Alerta"),
    ("CLONACION", "Posible clonación: Alerta"),
]


def registrar_escenario(placa: str, escenario: str, tipo: str):
    hoy = date.today()
    db.guardar_vehiculo(dict(placa=placa, naturaleza="nacional", tipo=tipo, servicio="Particular",
                             marca="(prueba)", linea="(prueba)", modelo=2020, color="—", ciudad="—"))
    for doc in ("SOAT", "Revisión técnico-mecánica"):
        vence = hoy - timedelta(days=30) if (escenario == "DOCUMENTOS_VENCIDOS" and doc == "SOAT") else hoy + timedelta(days=200)
        db.agregar("documentos", {"placa": placa, "documento": doc, "vence": vence.isoformat()})
    if escenario == "MULTAS_DEUDA":
        db.agregar("multas", {"placa": placa, "codigo": "C29", "descripcion": "Exceso de velocidad (registro de prueba)",
                              "valor": 604200, "fecha": hoy.isoformat(), "estado": "Pendiente", "inmoviliza": 0})
    if escenario == "ACTO_ILEGAL":
        db.agregar("reportes", {"placa": placa, "tipo": "hurto", "descripcion": "Reportado como hurtado (registro de prueba)",
                                "fecha": hoy.isoformat(), "fuente": "Base de prueba", "activo": 1})
    if escenario == "CLONACION":
        db.agregar("reportes", {"placa": placa, "tipo": "clonacion", "descripcion": "Placa reportada en otro vehículo (registro de prueba)",
                                "fecha": hoy.isoformat(), "fuente": "Base de prueba", "activo": 1})


def b64(img):
    h, w = img.shape[:2]
    e = 640 / max(h, w)
    ok, buf = cv2.imencode(".jpg", cv2.resize(img, (int(w * e), int(h * e))), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return base64.b64encode(buf).decode()


def main(rutas):
    db.inicializar()
    filas = []
    for i, ruta in enumerate(rutas):
        img = cv2.imread(str(ruta))
        escenario, nombre = ESCENARIOS[i % len(ESCENARIOS)]
        # 1) el sistema lee la placa (sin registro todavía)
        r0 = pipeline.procesar_imagen(img, anonimizar=True, origen="prueba")
        placa = r0["placa"]
        if not placa:
            filas.append((ruta, nombre, "(no leída)", None, r0))
            continue
        # 2) se crea el registro de prueba y se repite el cruce
        registrar_escenario(placa, escenario, (r0["clasificacion"] or {}).get("tipo", "carro"))
        r = pipeline.procesar_imagen(img, anonimizar=True, origen="prueba")
        filas.append((ruta, nombre, placa, r["alerta"], r))
        a = r["alerta"]
        print(f"{Path(ruta).name[:40]:40s} placa={placa:8s} esperado={escenario:20s} obtenido={a['categoria']:20s} "
              f"{'OK' if a['categoria'] == escenario else 'DIFERENTE'}")

    html = ["<html><meta charset='utf-8'><body style='font-family:Arial;max-width:1100px;margin:auto'>",
            "<h1>PlateGuardAI · Prueba de cruce de registros y alertas</h1>",
            "<p>Fotos reales del dataset. Registros de la base de datos <b>ficticios</b>, creados solo para la prueba.</p>"]
    for ruta, nombre, placa, a, r in filas:
        info = CATEGORIAS_ALERTA[a["categoria"]] if a else None
        cl = r["clasificacion"] or {}
        html.append(f"<div style='display:flex;gap:16px;border:1px solid #ccc;margin:12px 0;padding:10px'>"
                    f"<img src='data:image/jpeg;base64,{b64(r['anotada'])}' style='width:420px'>"
                    f"<div><p><b>Escenario de prueba:</b> {nombre}</p><p><b>Placa leída:</b> {placa}</p>"
                    f"<p><b>Clasificación:</b> {cl.get('naturaleza', '—')} · {cl.get('tipo', '—')}</p>")
        if info:
            html.append(f"<div style='background:{info['color']};color:white;padding:8px 12px'>"
                        f"<b>{info['codigo']} · {info['titulo']}</b><br>Protocolo: {info['protocolo']}</div>"
                        + "".join(f"<p>• {h['detalle']} <i>({h['fuente']})</i></p>" for h in a["hallazgos"]))
        html.append("</div></div>")
    destino = RAIZ / "data" / "pruebas" / "reporte_alertas.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("".join(html), encoding="utf-8")
    print("Reporte:", destino)


if __name__ == "__main__":
    main(sys.argv[1:])
