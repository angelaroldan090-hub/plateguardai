"""Lectura de caracteres (OCR) de la placa recortada.

Motor preferido: EasyOCR (pip install easyocr). Respaldo: Tesseract (pytesseract).
Incluye corrección por posición según el formato colombiano (letras/dígitos).
"""
from __future__ import annotations

import re

import cv2
import numpy as np

_EASY = None

A_DIGITO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7", "A": "4"}
A_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "7": "T", "4": "A"}


def _easyocr():
    global _EASY
    if _EASY is None:
        try:
            import easyocr  # type: ignore
            _EASY = easyocr.Reader(["es", "en"], gpu=False, verbose=False)
        except Exception:
            _EASY = False
    return _EASY or None


def motor_disponible() -> str:
    if _easyocr():
        return "EasyOCR"
    try:
        import pytesseract  # type: ignore
        pytesseract.get_tesseract_version()
        return "Tesseract"
    except Exception:
        return "Ninguno (instale easyocr o tesseract)"


def preparar_recorte(recorte_bgr: np.ndarray) -> np.ndarray:
    h, w = recorte_bgr.shape[:2]
    escala = max(1.0, 300 / max(w, 1))
    x = cv2.resize(recorte_bgr, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
    gris = cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)
    gris = cv2.createCLAHE(2.0, (4, 4)).apply(gris)
    gris = cv2.GaussianBlur(gris, (3, 3), 0)
    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Placas colombianas: letras negras sobre fondo claro -> fondo blanco
    if binaria.mean() < 127:
        binaria = 255 - binaria
    return binaria


def segmentar_caracteres(binaria: np.ndarray):
    """Segmenta los caracteres (componentes conexas) y descarta marco, tornillos y
    el texto pequeño de la ciudad. Devuelve (cajas, imagen_limpia_con_padding)."""
    inv = 255 - binaria  # caracteres en blanco
    H, W = inv.shape
    # borrar el marco de la placa (líneas largas horizontales/verticales) para que
    # no se "pegue" a los caracteres de los extremos
    lineas_h = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(W * 0.5), 1)))
    lineas_v = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(H * 0.95))))
    inv = cv2.subtract(inv, cv2.dilate(cv2.bitwise_or(lineas_h, lineas_v), np.ones((3, 3), np.uint8)))
    binaria = 255 - inv
    n, _, stats, _ = cv2.connectedComponentsWithStats(inv, 8)
    cajas = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (0.2 * H <= h <= 0.9 * H):
            continue
        if w > 0.4 * W or w < 0.015 * W or area < 30:
            continue
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:  # toca el borde -> marco
            continue
        cajas.append((x, y, w, h))
    if not cajas:
        return [], binaria
    # conservar los caracteres de altura similar a la mediana (quita texto de la ciudad)
    hm = np.median([c[3] for c in cajas])
    cajas = sorted([c for c in cajas if 0.6 * hm <= c[3] <= 1.5 * hm], key=lambda c: (c[1] // max(hm, 1), c[0]))
    if not cajas:
        return [], binaria
    limpia = np.full_like(binaria, 255)
    for x, y, w, h in cajas:
        limpia[y:y + h, x:x + w] = binaria[y:y + h, x:x + w]
    x1 = min(c[0] for c in cajas); y1 = min(c[1] for c in cajas)
    x2 = max(c[0] + c[2] for c in cajas); y2 = max(c[1] + c[3] for c in cajas)
    limpia = cv2.copyMakeBorder(limpia[y1:y2, x1:x2], 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return cajas, limpia


def _dos_lineas(cajas) -> bool:
    if len(cajas) < 4:
        return False
    ys = sorted(c[1] for c in cajas)
    hm = np.median([c[3] for c in cajas])
    return (ys[-1] - ys[0]) > 0.8 * hm


def _limpiar(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", t.upper())


FORMATOS_CO = [
    ("carro", "LLLDDD"),   # ABC123
    ("moto", "LLLDDL"),    # ABC12D
    ("moto", "LLLDD"),     # ABC12 (antigua)
]


def _ajustar(cad: str, patron: str) -> tuple[str, int]:
    """Aplica el patrón L/D carácter por carácter; devuelve (texto, n_cambios) o ('', 99) si no es posible."""
    out, cambios = [], 0
    for c, t in zip(cad, patron):
        if t == "L":
            if c.isalpha():
                out.append(c)
            elif c in A_LETRA:
                out.append(A_LETRA[c]); cambios += 1
            else:
                return "", 99
        else:
            if c.isdigit():
                out.append(c)
            elif c in A_DIGITO:
                out.append(A_DIGITO[c]); cambios += 1
            else:
                return "", 99
    return "".join(out), cambios


def candidatos_placa(texto: str) -> list[tuple[str, str, int]]:
    """Todas las placas colombianas posibles dentro del texto leído: (placa, tipo, cambios).
    Ej.: 'IGNP75F' -> GNP75F (moto). Así se descartan bordes, tornillos o letras de la ciudad."""
    t = _limpiar(texto)
    res = []
    for tipo, patron in FORMATOS_CO:
        n = len(patron)
        for i in range(0, max(1, len(t) - n + 1)):
            cad = t[i:i + n]
            if len(cad) < n:
                continue
            placa, cambios = _ajustar(cad, patron)
            if placa:
                # penaliza correcciones, caracteres sobrantes y el formato antiguo de moto
                costo = cambios * 2 + (len(t) - n) + (2 if patron == "LLLDD" else 0)
                res.append((placa, tipo, costo))
    return sorted(res, key=lambda r: r[2])


def corregir_formato_colombiano(texto: str) -> str:
    """Mejor placa colombiana dentro del texto leído; si no hay ninguna, el texto limpio (posible placa extranjera)."""
    import re

    from .config import FORMATOS_PLACA
    t = _limpiar(texto)
    # Placa extranjera completa (formatos específicos, no el genérico): se respeta tal cual
    for p in FORMATOS_PLACA["internacional_carro"] + FORMATOS_PLACA["internacional_moto"]:
        if not p.startswith("^[A-Z0-9]") and re.match(p, t):
            if not any(c[2] == 0 for c in candidatos_placa(t)):
                return t
    c = candidatos_placa(t)
    return c[0][0] if c else t


def _costo(t: str) -> int:
    c = candidatos_placa(t)
    return c[0][2] if c else 99


def leer_placa(recorte_bgr: np.ndarray, corregir: bool = True) -> dict:
    binaria = preparar_recorte(recorte_bgr)
    cajas, limpia = segmentar_caracteres(binaria)
    dos_lineas = _dos_lineas(cajas)
    entrada = limpia if cajas else binaria
    texto, conf, motor = "", 0.0, motor_disponible()

    lector = _easyocr()
    if lector:
        def _leer_easy(imagen):
            res = lector.readtext(imagen, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", detail=1)
            # se toman los 2 trozos más grandes (descarta el nombre de la ciudad)
            res = sorted(res, key=lambda r: (r[0][2][1] - r[0][0][1]) * len(r[1]), reverse=True)[:2]
            res = [r for r in res if len(_limpiar(r[1])) >= 2]
            if not res:
                return "", 0.0
            # se prueban los órdenes posibles y se queda el que forma una placa válida
            # (en placas inclinadas o de 2 líneas el orden por posición no es confiable)
            opciones = ["".join(r[1] for r in res)]
            if len(res) == 2:
                opciones.append(res[1][1] + res[0][1])
            return min(opciones, key=_costo), float(np.mean([r[2] for r in res]))

        # se lee la versión segmentada y la binarizada; gana la que forma una placa válida
        lecturas = [_leer_easy(entrada)]
        if cajas:
            lecturas.append(_leer_easy(binaria))
        texto, conf = min(lecturas, key=lambda tc: (_costo(tc[0]), -tc[1]))
    else:
        try:
            import pytesseract  # type: ignore
            psm = 6 if dos_lineas else 7
            cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            texto = pytesseract.image_to_string(entrada, config=cfg)
            data = pytesseract.image_to_data(entrada, config=cfg, output_type=pytesseract.Output.DICT)
            confs = [float(c) for w, c in zip(data["text"], data["conf"]) if str(w).strip() and float(c) >= 0]
            conf = float(np.mean(confs) / 100) if confs else (0.5 if texto.strip() else 0.0)
        except Exception as e:  # pragma: no cover
            motor = f"error: {e}"

    bruto = _limpiar(texto)
    final = corregir_formato_colombiano(bruto) if corregir else bruto
    return {"texto": final, "texto_bruto": bruto, "confianza": round(conf, 3), "motor": motor, "binaria": binaria,
            "segmentada": entrada, "n_caracteres": len(cajas), "dos_lineas": dos_lineas}
