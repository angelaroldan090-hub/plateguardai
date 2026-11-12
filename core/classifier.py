"""Sistema de clasificación: naturaleza de la placa (nacional/internacional) y tipo de vehículo (carro/moto).

Combina tres fuentes de evidencia:
  1. CNN entrenada (models/clasificador_placas.keras) si existe.
  2. Formato del texto leído (regex por país / tipo).
  3. Geometría y color del recorte (relación de aspecto, color de fondo).
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from .config import CLASES_VEHICULO, COLORES_PLACA_CO, FORMATOS_PLACA, MODELS_DIR

_CNN = None


def _cargar_cnn():
    """Clasificador entrenado: models/clasificador_placas.onnx (OpenCV DNN) o .keras (TensorFlow)."""
    global _CNN
    if _CNN is None:
        onnx = MODELS_DIR / "clasificador_placas.onnx"
        keras = MODELS_DIR / "clasificador_placas.keras"
        try:
            if onnx.exists():
                import json
                clases = json.loads((MODELS_DIR / "clasificador_clases.json").read_text())
                tam = clases.get("tam", 128) if isinstance(clases, dict) else 128
                nombres = clases["clases"] if isinstance(clases, dict) else clases
                _CNN = ("onnx", cv2.dnn.readNetFromONNX(str(onnx)), nombres, tam)
            elif keras.exists():
                import tensorflow as tf  # type: ignore
                _CNN = ("keras", tf.keras.models.load_model(keras), CLASES_VEHICULO, None)
            else:
                _CNN = False
        except Exception:
            _CNN = False
    return _CNN or None


def motor_disponible() -> str:
    return "CNN entrenada + reglas" if _cargar_cnn() else "Reglas (formato + geometría + color)"


def color_fondo(recorte_bgr: np.ndarray) -> str:
    hsv = cv2.cvtColor(cv2.resize(recorte_bgr, (120, 60)), cv2.COLOR_BGR2HSV)
    centro = hsv[10:50, 10:110].reshape(-1, 3)
    h, s, v = np.median(centro, axis=0)
    if s < 50 and v > 150:
        return "blanco"
    if 15 <= h <= 40 and s >= 80:
        return "amarillo"
    if 90 <= h <= 130 and s >= 80:
        return "azul"
    if (h <= 8 or h >= 165) and s >= 80:
        return "rojo"
    if 40 < h < 90 and s >= 80:
        return "verde"
    return "indeterminado"


def por_formato(texto: str) -> dict[str, float]:
    """Puntaje por clase según qué formato de placa coincide con el texto."""
    puntajes = {c: 0.0 for c in CLASES_VEHICULO}
    for clase, patrones in FORMATOS_PLACA.items():
        for p in patrones:
            if re.match(p, texto or ""):
                # el patrón genérico internacional pesa menos
                peso = 0.4 if p.startswith("^[A-Z0-9]") else (0.6 if p == r"^[A-Z]{3}\d{2}$" else 1.0)
                puntajes[clase] = max(puntajes[clase], peso)
    return puntajes


def por_geometria(recorte_bgr: np.ndarray) -> dict[str, float]:
    h, w = recorte_bgr.shape[:2]
    ar = w / float(max(h, 1))
    # placa de carro CO 33x17 cm (ar ~1.9 y más ancha en foto); moto 20x15 cm (ar ~1.3)
    p_moto = float(np.clip((2.1 - ar) / 0.8, 0, 1))
    return {"nacional_carro": 1 - p_moto, "internacional_carro": 1 - p_moto,
            "nacional_moto": p_moto, "internacional_moto": p_moto}


def por_cnn(recorte_bgr: np.ndarray) -> dict[str, float] | None:
    m = _cargar_cnn()
    if not m:
        return None
    tipo, modelo, nombres, tam = m
    if tipo == "onnx":
        # mismo preprocesamiento que en el entrenamiento: cuadrado con relleno, RGB, /255
        h, w = recorte_bgr.shape[:2]
        lado = max(h, w)
        cuadro = np.zeros((lado, lado, 3), np.uint8)
        cuadro[(lado - h) // 2:(lado - h) // 2 + h, (lado - w) // 2:(lado - w) // 2 + w] = recorte_bgr
        blob = cv2.dnn.blobFromImage(cuadro, 1 / 255.0, (tam, tam), swapRB=True)
        modelo.setInput(blob)
        probs = modelo.forward()[0]
    else:
        x = cv2.resize(recorte_bgr, (128, 64)).astype("float32") / 255.0
        probs = modelo.predict(x[None, ...], verbose=0)[0]
    p = {c: 0.0 for c in CLASES_VEHICULO}
    for n, v in zip(nombres, probs):
        if n in p:
            p[n] = float(v)
    return p


def clasificar(texto: str, recorte_bgr: np.ndarray) -> dict:
    """Combina las fuentes de evidencia de forma separada por eje:
    - Naturaleza (nacional / internacional): CNN (muy confiable: separa placas colombianas y extranjeras)
      + formato del texto + color de fondo.
    - Tipo (carro / moto): formato del texto (ABC123 vs ABC12D) + geometría del recorte + CNN. Desde que la
      CNN se reentrenó con las placas reales de moto del set1, su voto pesa la mitad (antes 15 %).
    """
    f = por_formato(texto)
    g = por_geometria(recorte_bgr)
    color = color_fondo(recorte_bgr)
    c = por_cnn(recorte_bgr)

    # --- naturaleza ---
    nac_fmt = max(f["nacional_carro"], f["nacional_moto"])
    int_fmt = max(f["internacional_carro"], f["internacional_moto"])
    if nac_fmt or int_fmt:
        p_nac_reglas = (nac_fmt + 0.05) / (nac_fmt + int_fmt + 0.1)
    else:
        p_nac_reglas = 0.5
    if color in ("amarillo",):
        p_nac_reglas = 0.7 * p_nac_reglas + 0.3
    if c:
        p_nac_cnn = c["nacional_carro"] + c["nacional_moto"]
        p_nac = 0.35 * p_nac_reglas + 0.65 * p_nac_cnn
    else:
        p_nac = p_nac_reglas

    # --- tipo ---
    moto_fmt, carro_fmt = max(f["nacional_moto"], f["internacional_moto"]), max(f["nacional_carro"], f["internacional_carro"])
    if moto_fmt > carro_fmt:
        p_moto = 0.9 * moto_fmt
    elif carro_fmt > moto_fmt:
        p_moto = 0.1 * (1 - carro_fmt) + 0.05
    else:
        p_moto = g["nacional_moto"]
    p_moto = 0.8 * p_moto + 0.2 * g["nacional_moto"]
    if c:
        p_moto = 0.5 * p_moto + 0.5 * c["nacional_moto"]

    probs = {
        "nacional_carro": p_nac * (1 - p_moto), "nacional_moto": p_nac * p_moto,
        "internacional_carro": (1 - p_nac) * (1 - p_moto), "internacional_moto": (1 - p_nac) * p_moto,
    }
    probs = {k: round(v, 3) for k, v in probs.items()}
    clase = max(probs, key=probs.get)
    naturaleza, tipo = clase.split("_")
    servicio = COLORES_PLACA_CO.get(color, "No determinado") if naturaleza == "nacional" else "—"
    return {
        "clase": clase,
        "naturaleza": naturaleza,
        "tipo": tipo,
        "color_fondo": color,
        "servicio": servicio,
        "probabilidades": probs,
        "probabilidades_cnn": c,
        "motor": motor_disponible(),
    }
