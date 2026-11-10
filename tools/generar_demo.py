"""Genera imágenes sintéticas de prueba (escena con placa colombiana) en data/demo/."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import DATA_DIR  # noqa: E402

DEMO = DATA_DIR / "demo"


def placa(texto, moto=False, fondo=(0, 205, 245)):
    w, h = (200, 150) if moto else (330, 160)
    img = np.full((h, w, 3), fondo, np.uint8)
    cv2.rectangle(img, (4, 4), (w - 5, h - 5), (20, 20, 20), 4)
    if moto:
        cv2.putText(img, texto[:3], (35, 68), cv2.FONT_HERSHEY_DUPLEX, 2.0, (15, 15, 15), 5)
        cv2.putText(img, texto[3:], (35, 128), cv2.FONT_HERSHEY_DUPLEX, 2.0, (15, 15, 15), 5)
    else:
        cv2.putText(img, f"{texto[:3]} {texto[3:]}", (28, 105), cv2.FONT_HERSHEY_DUPLEX, 2.1, (15, 15, 15), 6)
        cv2.putText(img, "MEDELLIN", (115, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (15, 15, 15), 2)
    return img


def escena(texto, moto=False, fondo_placa=(0, 205, 245), carroceria=(60, 60, 150)):
    H, W = 720, 1080
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (90, 95, 100)
    cv2.rectangle(img, (150, 120), (930, 650), carroceria, -1)
    cv2.rectangle(img, (230, 160), (850, 360), (40, 40, 45), -1)
    cv2.circle(img, (260, 430), 50, (220, 230, 240), -1)
    cv2.circle(img, (820, 430), 50, (220, 230, 240), -1)
    p = placa(texto, moto, fondo_placa)
    ph, pw = p.shape[:2]
    y, x = 470, (W - pw) // 2
    img[y:y + ph, x:x + pw] = p
    ruido = np.random.normal(0, 6, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + ruido, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    DEMO.mkdir(parents=True, exist_ok=True)
    casos = [("KTM123", False, (0, 205, 245)), ("HJK321", False, (0, 205, 245)),
             ("MNB654", False, (0, 205, 245)), ("WPN456", False, (235, 235, 235)),
             ("ABC12D", True, (0, 205, 245)), ("EGX799", True, (0, 205, 245)),
             ("LUZ482", False, (0, 205, 245))]
    for t, moto, f in casos:
        cv2.imwrite(str(DEMO / f"demo_{t}.jpg"), escena(t, moto, f))
    print("Imágenes de prueba en", DEMO)
