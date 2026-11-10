"""Manejo del dataset del profesor (Drive: reto_placas/set1..set4, formato COCO de Roboflow).

Estructura esperada (descargue la carpeta del Drive y descomprímala en data/reto_placas):
    data/reto_placas/set1/_annotations.coco.json + imágenes
    data/reto_placas/set2/...
Funciones:
  - cargar(): lee todas las anotaciones COCO en un DataFrame.
  - recortar(): extrae el recorte de cada placa anotada.
  - etiquetas de clase (nacional/internacional x carro/moto) en data/etiquetas_clase.csv
  - exportar_yolo(): convierte a formato YOLO para entrenar el detector.
  - exportar_augmentado(): genera recortes aumentados balanceando las clases.
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import cv2
import pandas as pd

from .config import CLASES_VEHICULO, DATA_DIR, DATASET_DIR
from .preprocessing import aplicar_clahe, augment_aleatorio

ETIQUETAS_CSV = DATA_DIR / "etiquetas_clase.csv"


def sets_disponibles(raiz: Path = DATASET_DIR) -> list[Path]:
    if not raiz.exists():
        return []
    return sorted(p.parent for p in raiz.rglob("_annotations.coco.json"))


def cargar(raiz: Path = DATASET_DIR) -> pd.DataFrame:
    filas = []
    for carpeta in sets_disponibles(raiz):
        coco = json.loads((carpeta / "_annotations.coco.json").read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in coco.get("categories", [])}
        imgs = {i["id"]: i for i in coco.get("images", [])}
        con_anot = set()
        for a in coco.get("annotations", []):
            im = imgs.get(a["image_id"])
            if not im:
                continue
            con_anot.add(a["image_id"])
            x, y, w, h = a["bbox"]
            filas.append({
                "set": carpeta.name, "archivo": im["file_name"], "ruta": str(carpeta / im["file_name"]),
                "ancho_img": im.get("width"), "alto_img": im.get("height"),
                "categoria_coco": cats.get(a["category_id"], str(a["category_id"])),
                "x": int(x), "y": int(y), "w": int(w), "h": int(h),
                "aspecto": round(w / max(h, 1), 2), "ann_id": a["id"],
            })
        for iid, im in imgs.items():
            if iid not in con_anot:
                filas.append({"set": carpeta.name, "archivo": im["file_name"], "ruta": str(carpeta / im["file_name"]),
                              "ancho_img": im.get("width"), "alto_img": im.get("height"),
                              "categoria_coco": "(sin anotación)", "x": None, "y": None, "w": None, "h": None,
                              "aspecto": None, "ann_id": None})
    df = pd.DataFrame(filas)
    if not df.empty:
        df["id"] = df["set"] + "/" + df["archivo"] + "#" + df["ann_id"].astype(str)
    return df


def recortar(fila, margen: float = 0.05):
    img = cv2.imread(fila["ruta"])
    if img is None or pd.isna(fila["x"]):
        return None
    x, y, w, h = int(fila["x"]), int(fila["y"]), int(fila["w"]), int(fila["h"])
    mx, my = int(w * margen), int(h * margen)
    H, W = img.shape[:2]
    return img[max(0, y - my):min(H, y + h + my), max(0, x - mx):min(W, x + w + mx)]


# ---------------------------------------------------------------------------
# Etiquetas de clase (segmentación pedida por el reto)
# ---------------------------------------------------------------------------
def cargar_etiquetas() -> dict[str, str]:
    if ETIQUETAS_CSV.exists():
        df = pd.read_csv(ETIQUETAS_CSV)
        return dict(zip(df["id"], df["clase"]))
    return {}


def guardar_etiqueta(id_: str, clase: str):
    et = cargar_etiquetas()
    et[id_] = clase
    pd.DataFrame({"id": list(et), "clase": list(et.values())}).to_csv(ETIQUETAS_CSV, index=False)


def guardar_etiquetas(nuevas: dict[str, str]):
    et = cargar_etiquetas()
    et.update(nuevas)
    pd.DataFrame({"id": list(et), "clase": list(et.values())}).to_csv(ETIQUETAS_CSV, index=False)


def pesos_de_clase(conteos: dict[str, int]) -> dict[str, float]:
    """Pesos inversamente proporcionales a la frecuencia (manejo de clases desbalanceadas)."""
    total = sum(conteos.values())
    n = len([c for c in conteos.values() if c > 0]) or 1
    return {c: round(total / (n * v), 3) if v else 0.0 for c, v in conteos.items()}


# ---------------------------------------------------------------------------
# Exportaciones
# ---------------------------------------------------------------------------
def exportar_yolo(df: pd.DataFrame, destino: Path, val_split: float = 0.2, semilla: int = 42) -> Path:
    """Formato YOLO (una sola clase: 'placa') para entrenar el detector con ultralytics."""
    destino = Path(destino)
    if destino.exists():
        shutil.rmtree(destino)
    imgs = df.dropna(subset=["x"]).groupby("ruta")
    rutas = list(imgs.groups)
    random.Random(semilla).shuffle(rutas)
    n_val = int(len(rutas) * val_split)
    for i, ruta in enumerate(rutas):
        parte = "val" if i < n_val else "train"
        (destino / "images" / parte).mkdir(parents=True, exist_ok=True)
        (destino / "labels" / parte).mkdir(parents=True, exist_ok=True)
        g = imgs.get_group(ruta)
        W, H = g.iloc[0]["ancho_img"], g.iloc[0]["alto_img"]
        nombre = f"{g.iloc[0]['set']}_{Path(ruta).name}"
        shutil.copy(ruta, destino / "images" / parte / nombre)
        lineas = [f"0 {(r.x + r.w / 2) / W:.6f} {(r.y + r.h / 2) / H:.6f} {r.w / W:.6f} {r.h / H:.6f}" for r in g.itertuples()]
        (destino / "labels" / parte / (Path(nombre).stem + ".txt")).write_text("\n".join(lineas))
    (destino / "data.yaml").write_text(
        f"path: {destino.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: placa\n")
    return destino / "data.yaml"


def exportar_recortes(df: pd.DataFrame, etiquetas: dict[str, str], destino: Path,
                      objetivo_por_clase: int = 300, usar_clahe: bool = True) -> dict[str, int]:
    """Recortes por clase en carpetas (formato ImageFolder) + augmentación hasta balancear."""
    destino = Path(destino)
    if destino.exists():
        shutil.rmtree(destino)
    por_clase = {c: [] for c in CLASES_VEHICULO}
    for _, fila in df.dropna(subset=["x"]).iterrows():
        clase = etiquetas.get(fila["id"])
        if clase in por_clase:
            rec = recortar(fila)
            if rec is not None and rec.size:
                por_clase[clase].append(aplicar_clahe(rec) if usar_clahe else rec)
    conteo = {}
    for clase, recs in por_clase.items():
        carpeta = destino / clase
        carpeta.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(recs):
            cv2.imwrite(str(carpeta / f"orig_{i:05d}.jpg"), r)
        k = 0
        while recs and len(recs) + k < objetivo_por_clase:
            aug, _ = augment_aleatorio(random.choice(recs), random.randint(1, 3))
            cv2.imwrite(str(carpeta / f"aug_{k:05d}.jpg"), aug)
            k += 1
        conteo[clase] = len(recs) + k
    return conteo
