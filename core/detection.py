"""Detección de la placa en la imagen.

Dos motores:
  1. YOLO (ultralytics) si existe models/placas.pt  -> se entrena con las anotaciones COCO del Drive.
  2. Clásico con OpenCV (color + bordes + geometría) como respaldo, sin entrenamiento.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import MODELS_DIR

_YOLO = None


@dataclass
class Deteccion:
    x: int
    y: int
    w: int
    h: int
    score: float
    metodo: str
    recorte: np.ndarray = field(repr=False, default=None)

    @property
    def caja(self):
        return self.x, self.y, self.w, self.h


def _cargar_yolo():
    """Detector entrenado. Prioridad: models/placas.onnx (OpenCV DNN, liviano, sirve en la web)
    y luego models/placas.pt (requiere ultralytics)."""
    global _YOLO
    if _YOLO is not None:
        return _YOLO or None
    onnx = MODELS_DIR / "placas.onnx"
    pt = MODELS_DIR / "placas.pt"
    try:
        if onnx.exists():
            _YOLO = ("onnx", cv2.dnn.readNetFromONNX(str(onnx)))
        elif pt.exists():
            from ultralytics import YOLO  # type: ignore
            _YOLO = ("pt", YOLO(str(pt)))
        else:
            _YOLO = False
    except Exception:
        _YOLO = False
    return _YOLO or None


def motor_disponible() -> str:
    m = _cargar_yolo()
    return f"YOLOv8 entrenado ({'ONNX' if m[0] == 'onnx' else 'PyTorch'})" if m else "Clásico OpenCV"


# ---------------------------------------------------------------------------
TAM_YOLO = 512  # tamaño de entrada con el que se exportó el modelo


def _detectar_yolo(img, conf=0.30):
    tipo, modelo = _cargar_yolo()
    if tipo == "pt":
        res = modelo.predict(img, conf=conf, verbose=False)[0]
        return [Deteccion(*map(int, (b.xyxy[0][0], b.xyxy[0][1], b.xyxy[0][2] - b.xyxy[0][0], b.xyxy[0][3] - b.xyxy[0][1])),
                          float(b.conf[0]), "yolo") for b in res.boxes]
    # ONNX con OpenCV DNN: letterbox -> inferencia -> NMS
    h, w = img.shape[:2]
    r = TAM_YOLO / max(h, w)
    nw, nh = int(round(w * r)), int(round(h * r))
    lienzo = np.full((TAM_YOLO, TAM_YOLO, 3), 114, np.uint8)
    dx, dy = (TAM_YOLO - nw) // 2, (TAM_YOLO - nh) // 2
    lienzo[dy:dy + nh, dx:dx + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    blob = cv2.dnn.blobFromImage(lienzo, 1 / 255.0, (TAM_YOLO, TAM_YOLO), swapRB=True)
    modelo.setInput(blob)
    salida = modelo.forward()[0]          # (5, N): cx, cy, w, h, score
    salida = salida.T
    cajas, scores = [], []
    for cx, cy, bw, bh, sc in salida[salida[:, 4] >= conf]:
        x = (cx - bw / 2 - dx) / r
        y = (cy - bh / 2 - dy) / r
        cajas.append([int(x), int(y), int(bw / r), int(bh / r)])
        scores.append(float(sc))
    idx = cv2.dnn.NMSBoxes(cajas, scores, conf, 0.45)
    dets = []
    for i in np.array(idx).flatten():
        x, y, bw, bh = cajas[i]
        x, y = max(0, x), max(0, y)
        bw, bh = min(bw, w - x), min(bh, h - y)
        if bw > 4 and bh > 4:
            dets.append(Deteccion(x, y, bw, bh, round(scores[i], 3), "yolo"))
    return dets


def _mascara_color(hsv):
    """Fondos típicos de placa: amarillo (particular CO) y blanco (público / internacionales)."""
    amarillo = cv2.inRange(hsv, (15, 80, 90), (40, 255, 255))
    blanco = cv2.inRange(hsv, (0, 0, 170), (180, 45, 255))
    return amarillo, blanco


def _candidatos(mask, img_area, fuente):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if area < img_area * 0.002 or area > img_area * 0.5:
            continue
        ar = w / float(h)
        # carro ~ 2.0-5.0 (CO: 33x17 cm ≈ 1.95; foto en ángulo amplía); moto ~ 1.0-2.0
        if not (0.9 <= ar <= 6.0):
            continue
        relleno = cv2.contourArea(c) / float(area)
        if relleno < 0.45:
            continue
        out.append((x, y, w, h, ar, relleno, fuente))
    return out


def _densidad_bordes(gris_recorte):
    if gris_recorte.size == 0:
        return 0.0
    bordes = cv2.Canny(gris_recorte, 80, 200)
    return float(bordes.mean() / 255.0)


def _detectar_clasico(img):
    h_img, w_img = img.shape[:2]
    area = h_img * w_img
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    amarillo, blanco = _mascara_color(hsv)
    # Amarillo estricto: separa la placa del entorno (pavimento, carrocería) en fotos reales
    estricto = cv2.inRange(hsv, (15, 100, 110), (38, 255, 255))
    estricto = cv2.morphologyEx(estricto, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    cands = (_candidatos(estricto, area, "amarillo") + _candidatos(amarillo, area, "amarillo")
             + _candidatos(blanco, area, "blanco"))

    # Candidatos por bordes (útil cuando el color no es confiable: noche, placas sucias)
    bil = cv2.bilateralFilter(gris, 11, 17, 17)
    edged = cv2.Canny(bil, 30, 200)
    cnts, _ = cv2.findContours(edged, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:40]:
        approx = cv2.approxPolyDP(c, 0.018 * cv2.arcLength(c, True), True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            ar = w / float(max(h, 1))
            if 1.0 <= ar <= 6.0 and area * 0.002 < w * h < area * 0.4:
                cands.append((x, y, w, h, ar, 0.9, "bordes"))

    dets = []
    for x, y, w, h, ar, relleno, fuente in cands:
        dens = _densidad_bordes(gris[y:y + h, x:x + w])
        # los caracteres generan densidad de bordes media (ni lisa ni ruido total)
        s_dens = 1.0 - min(abs(dens - 0.18) / 0.18, 1.0)
        s_ar = 1.0 - min(min(abs(ar - 2.0), abs(ar - 1.5)) / 2.5, 1.0)
        s_color = 0.15 if fuente == "amarillo" else 0.0
        score = 0.45 * s_dens + 0.3 * s_ar + 0.25 * relleno + s_color
        dets.append(Deteccion(x, y, w, h, round(min(score, 0.99), 3), f"clásico-{fuente}"))
    return _nms(dets)


def _iou(a, b):
    ax2, ay2, bx2, by2 = a.x + a.w, a.y + a.h, b.x + b.w, b.y + b.h
    ix = max(0, min(ax2, bx2) - max(a.x, b.x))
    iy = max(0, min(ay2, by2) - max(a.y, b.y))
    inter = ix * iy
    return inter / float(a.w * a.h + b.w * b.h - inter + 1e-6)


def _nms(dets, umbral=0.3):
    dets = sorted(dets, key=lambda d: d.score, reverse=True)
    keep = []
    for d in dets:
        if all(_iou(d, k) < umbral for k in keep):
            keep.append(d)
    return keep


# ---------------------------------------------------------------------------
def detectar_placas(img_bgr: np.ndarray, max_resultados: int = 6, margen: float = 0.04):
    dets = _detectar_yolo(img_bgr) if _cargar_yolo() else []
    if not dets:  # respaldo: detector clásico (p. ej. placas muy cercanas o inclinadas)
        dets = _detectar_clasico(img_bgr)
    h_img, w_img = img_bgr.shape[:2]
    for d in dets:
        mx, my = int(d.w * margen), int(d.h * margen)
        x1, y1 = max(0, d.x - mx), max(0, d.y - my)
        x2, y2 = min(w_img, d.x + d.w + mx), min(h_img, d.y + d.h + my)
        d.recorte = img_bgr[y1:y2, x1:x2].copy()
    return sorted(dets, key=lambda d: d.score, reverse=True)[:max_resultados]


def dibujar(img_bgr, dets, textos=None):
    out = img_bgr.copy()
    grosor = max(2, out.shape[1] // 400)
    for i, d in enumerate(dets):
        color = (0, 220, 120) if i == 0 else (0, 180, 255)
        cv2.rectangle(out, (d.x, d.y), (d.x + d.w, d.y + d.h), color, grosor)
        etiqueta = (textos[i] if textos and i < len(textos) else None) or f"{d.score:.2f}"
        escala = max(0.6, out.shape[1] / 1400)
        (tw, th), _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, escala, 2)
        cv2.rectangle(out, (d.x, max(0, d.y - th - 10)), (d.x + tw + 8, d.y), color, -1)
        cv2.putText(out, etiqueta, (d.x + 4, d.y - 6), cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0), 2)
    return out
