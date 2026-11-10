"""Evaluación del sistema con imágenes reales (comparación detector clásico vs. YOLO entrenado).

Uso:
    python tools/evaluar_modelos.py --anotadas data/yolo/ds  (imágenes con cajas del profesor)
Calcula, sobre un conjunto de imágenes con cajas reales:
  - Detección: recall con IoU >= 0.5 (¿encontró la placa?) para el detector clásico y para YOLO.
  - Lectura: % de placas leídas con un formato válido (colombiano o extranjero conocido).
  - Tiempo promedio por imagen.
"""
import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import cv2  # noqa: E402

from core import classifier, detection, ocr, preprocessing  # noqa: E402


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter + 1e-6)


def evaluar(imagenes: list[tuple[Path, list]], usar_yolo: bool):
    original = detection._YOLO
    if not usar_yolo:
        detection._YOLO = False
    aciertos = total = formato_ok = 0
    t0 = time.perf_counter()
    for ruta, cajas in imagenes:
        img = cv2.imread(str(ruta))
        base = preprocessing.aplicar_clahe(preprocessing.reducir_ruido(img))
        dets = detection.detectar_placas(base)
        for caja in cajas:
            total += 1
            if any(iou(caja, d.caja) >= 0.5 for d in dets):
                aciertos += 1
        if dets:
            lect = [ocr.leer_placa(d.recorte)["texto"] for d in dets[:3]]
            if any(max(classifier.por_formato(t).values()) >= 0.6 for t in lect if t):
                formato_ok += 1
    detection._YOLO = original
    n = len(imagenes)
    return {"recall_deteccion": round(aciertos / max(total, 1), 3), "lectura_formato_valido": round(formato_ok / max(n, 1), 3),
            "seg_por_imagen": round((time.perf_counter() - t0) / max(n, 1), 3), "imagenes": n, "placas": total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anotadas", default=str(RAIZ / "data" / "yolo" / "ds"))
    ap.add_argument("--lista", help="json con la lista de ids a evaluar (p. ej. el split de validación)")
    ap.add_argument("--max", type=int, default=200)
    args = ap.parse_args()
    base = Path(args.anotadas)
    anot = json.loads((base / "anotaciones.json").read_text())
    ids = json.loads(Path(args.lista).read_text()) if args.lista else list(anot)
    imagenes = [(base / "images" / f"{k}.jpg", [b["bbox"] for b in anot[k]["cajas"] if b["bbox"]])
                for k in ids[: args.max] if any(b["bbox"] for b in anot[k]["cajas"])]
    res = {"clasico": evaluar(imagenes, usar_yolo=False)}
    if detection._cargar_yolo():
        res["yolo"] = evaluar(imagenes, usar_yolo=True)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
