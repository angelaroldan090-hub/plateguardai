"""Prepara el dataset del profesor para entrenar (se ejecuta sobre data/reto_placas).

- Elimina duplicados (set4 = set3; set2 está contenido en set3).
- Asigna la clase según el origen de la anotación:
    'placa'  (placas colombianas de carro)      -> nacional_carro
    'object' (placas brasileñas)                -> internacional_carro
    set1     (motos colombianas, sin cajas)     -> nacional_moto (cajas propuestas por el detector clásico)
- Reduce las imágenes a 1024 px de lado mayor y escala las cajas.
Salida: data/yolo/ds/images/*.jpg y data/yolo/ds/anotaciones.json
Uso: python tools/preparar_dataset.py [--motos]
"""
import hashlib
import json
import sys
from pathlib import Path

import cv2

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "data" / "reto_placas"
OUT = RAIZ / "data" / "yolo" / "ds"
MAX = 1024
CLASE = {"placa": "nacional_carro", "placas": "nacional_carro", "object": "internacional_carro",
         "placas-motos": "nacional_moto"}


def reducir(img):
    h, w = img.shape[:2]
    e = min(1.0, MAX / max(h, w))
    return (cv2.resize(img, (int(w * e), int(h * e)), interpolation=cv2.INTER_AREA) if e < 1 else img), e


def main(motos=False):
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    ann_path = OUT / "anotaciones.json"
    datos = json.loads(ann_path.read_text()) if ann_path.exists() else {}
    vistos = {}
    sets = ["set1"] if motos else ["set2", "set3", "set4"]
    for s in sets:
        coco = json.loads((SRC / s / "_annotations.coco.json").read_text())
        cats = {c["id"]: c["name"] for c in coco["categories"]}
        por_img = {}
        for a in coco["annotations"]:
            por_img.setdefault(a["image_id"], []).append(a)
        for im in coco["images"]:
            nombre = im["file_name"]
            clave = hashlib.md5(nombre.encode()).hexdigest()[:12]
            if clave in datos or clave in vistos:
                continue  # duplicado o ya procesado
            anns = por_img.get(im["id"], [])
            if not anns and not motos:
                continue
            img = cv2.imread(str(SRC / s / nombre))
            if img is None:
                continue
            red, e = reducir(img)
            cajas = [{"bbox": [round(v * e, 1) for v in a["bbox"]], "clase": CLASE.get(cats[a["category_id"]], "nacional_carro")}
                     for a in anns]
            if motos and not cajas:
                cajas = [{"bbox": None, "clase": "nacional_moto"}]  # se completa con el detector y revisión visual
            cv2.imwrite(str(OUT / "images" / f"{clave}.jpg"), red, [cv2.IMWRITE_JPEG_QUALITY, 90])
            vistos[clave] = {"origen": f"{s}/{nombre}", "ancho": red.shape[1], "alto": red.shape[0], "cajas": cajas}
            if len(vistos) % 50 == 0:
                datos.update(vistos); ann_path.write_text(json.dumps(datos)); vistos.clear()
                print("procesadas", len(datos), flush=True)
    datos.update(vistos)
    ann_path.write_text(json.dumps(datos))
    print("total", len(datos))


if __name__ == "__main__":
    main("--motos" in sys.argv)
