"""Preprocesamiento: limpieza con CLAHE, normalización y data augmentation para placas."""
from __future__ import annotations

import random

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------
def aplicar_clahe(img_bgr: np.ndarray, clip_limit: float = 2.0, tile: int = 8) -> np.ndarray:
    """CLAHE sobre el canal L (espacio LAB) para no distorsionar el color de la placa."""
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
    l2 = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)


def reducir_ruido(img_bgr: np.ndarray, fuerza: int = 7) -> np.ndarray:
    """Filtro bilateral: suaviza ruido conservando los bordes de los caracteres."""
    return cv2.bilateralFilter(img_bgr, d=9, sigmaColor=fuerza * 10, sigmaSpace=fuerza * 10)


def redimensionar(img: np.ndarray, ancho_max: int = 1280) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= ancho_max:
        return img
    escala = ancho_max / w
    return cv2.resize(img, (ancho_max, int(h * escala)), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def normalizar(img: np.ndarray, size: tuple[int, int] = (224, 224), modo: str = "minmax") -> np.ndarray:
    """Devuelve float32. modo='minmax' -> [0,1]; modo='zscore' -> media 0, desviación 1."""
    x = cv2.resize(img, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    if modo == "zscore":
        return (x - x.mean()) / (x.std() + 1e-6)
    return x / 255.0


def a_visible(x: np.ndarray) -> np.ndarray:
    """Convierte un tensor normalizado a uint8 para poder mostrarlo."""
    x = x.astype(np.float32)
    x = (x - x.min()) / (x.max() - x.min() + 1e-6)
    return (x * 255).astype(np.uint8)


def preprocesar(img_bgr: np.ndarray, clip_limit=2.0, tile=8, denoise=True) -> dict:
    """Pipeline completo; devuelve cada etapa para mostrarla en la interfaz."""
    etapas = {"original": img_bgr}
    x = redimensionar(img_bgr)
    if denoise:
        x = reducir_ruido(x)
        etapas["sin_ruido"] = x
    x = aplicar_clahe(x, clip_limit, tile)
    etapas["clahe"] = x
    etapas["normalizada"] = normalizar(x)
    return etapas


def histograma(img_bgr: np.ndarray) -> np.ndarray:
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.calcHist([gris], [0], None, [64], [0, 256]).flatten()


# ---------------------------------------------------------------------------
# Data augmentation específico para placas
#  - NO se usa volteo horizontal (invierte los caracteres y crea placas falsas)
#  - Se simulan condiciones reales de cámara en vía: ángulo, distancia,
#    movimiento, lluvia/suciedad, sombras, noche y compresión.
# ---------------------------------------------------------------------------
def aug_perspectiva(img, max_desplaz=0.12):
    h, w = img.shape[:2]
    d = max_desplaz
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[random.uniform(0, d) * w, random.uniform(0, d) * h],
                      [w - random.uniform(0, d) * w, random.uniform(0, d) * h],
                      [w - random.uniform(0, d) * w, h - random.uniform(0, d) * h],
                      [random.uniform(0, d) * w, h - random.uniform(0, d) * h]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def aug_rotacion(img, max_grados=10):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), random.uniform(-max_grados, max_grados), 1.0)
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def aug_desenfoque_movimiento(img, k=None):
    k = k or random.choice([5, 7, 9, 11])
    kernel = np.zeros((k, k), np.float32)
    kernel[k // 2, :] = 1.0 / k
    return cv2.filter2D(img, -1, kernel)


def aug_brillo_contraste(img, alpha=None, beta=None):
    alpha = alpha if alpha is not None else random.uniform(0.6, 1.4)
    beta = beta if beta is not None else random.uniform(-40, 40)
    return cv2.convertScaleAbs(img, alpha=alpha, beta=beta)


def aug_noche(img):
    oscuro = cv2.convertScaleAbs(img, alpha=0.45, beta=-20)
    ruido = np.random.normal(0, 12, img.shape).astype(np.int16)
    return np.clip(oscuro.astype(np.int16) + ruido, 0, 255).astype(np.uint8)


def aug_sombra(img):
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    x1, x2 = sorted(random.sample(range(w), 2))
    pts = np.array([[x1, 0], [x2, 0], [x2 + random.randint(-w // 4, w // 4), h], [x1, h]])
    cv2.fillPoly(mask, [pts], 255)
    out = img.copy()
    out[mask == 255] = (out[mask == 255] * 0.5).astype(np.uint8)
    return out


def aug_lluvia_suciedad(img, n=None):
    out = img.copy()
    h, w = img.shape[:2]
    for _ in range(n or random.randint(80, 200)):
        x, y = random.randint(0, w - 1), random.randint(0, h - 1)
        largo = random.randint(4, max(5, h // 15))
        c = random.randint(150, 220)
        cv2.line(out, (x, y), (x + 1, min(h - 1, y + largo)), (c, c, c), 1)
    return cv2.blur(out, (2, 2))


def aug_jpeg(img, calidad=None):
    calidad = calidad or random.randint(15, 45)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def aug_escala(img, factor=None):
    """Simula placa lejana: baja resolución y vuelve a subir."""
    factor = factor or random.uniform(0.25, 0.6)
    h, w = img.shape[:2]
    peq = cv2.resize(img, (max(8, int(w * factor)), max(8, int(h * factor))), interpolation=cv2.INTER_AREA)
    return cv2.resize(peq, (w, h), interpolation=cv2.INTER_LINEAR)


AUGMENTACIONES = {
    "Perspectiva (ángulo de cámara)": aug_perspectiva,
    "Rotación ±10°": aug_rotacion,
    "Desenfoque por movimiento": aug_desenfoque_movimiento,
    "Brillo / contraste": aug_brillo_contraste,
    "Condición nocturna": aug_noche,
    "Sombra parcial": aug_sombra,
    "Lluvia / suciedad": aug_lluvia_suciedad,
    "Compresión JPEG": aug_jpeg,
    "Distancia (baja resolución)": aug_escala,
}


def augment_aleatorio(img, n_transformaciones: int = 2):
    nombres = random.sample(list(AUGMENTACIONES), n_transformaciones)
    out = img
    for n in nombres:
        out = AUGMENTACIONES[n](out)
    return out, nombres
