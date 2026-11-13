"""Lectura de caracteres (OCR) de la placa recortada.

Motor preferido: red OCR especializada en placas (fast-plate-ocr, modelo CCT global en ONNX, MIT),
incluida en models/ocr_placas. Respaldos: EasyOCR y Tesseract.
Incluye corrección por posición según el formato colombiano (letras/dígitos).
"""
from __future__ import annotations

import re

import cv2
import numpy as np

_EASY = None
_PLACAS = None

A_DIGITO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7", "A": "4"}
A_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "7": "T", "4": "A"}


def _easyocr():
    global _EASY
    import os
    if os.environ.get("PLATEGUARD_OCR", "").lower() == "tesseract":   # forzar Tesseract (pruebas / web)
        return None
    if _EASY is None:
        try:
            import easyocr  # type: ignore
            _EASY = easyocr.Reader(["es", "en"], gpu=False, verbose=False)
        except Exception:
            _EASY = False
    return _EASY or None


def _ocr_placas():
    """Red OCR entrenada solo con placas (CCT, fast-plate-ocr). Funciona igual en la web y en el computador."""
    global _PLACAS
    import os
    if os.environ.get("PLATEGUARD_OCR", "").lower() in ("tesseract", "easyocr"):
        return None
    if _PLACAS is None:
        try:
            from pathlib import Path
            from fast_plate_ocr import LicensePlateRecognizer  # type: ignore
            d = Path(__file__).resolve().parent.parent / "models" / "ocr_placas"
            _PLACAS = LicensePlateRecognizer(onnx_model_path=d / "cct_s_v2_global.onnx",
                                             plate_config_path=d / "cct_s_v2_global_plate_config.yaml",
                                             device="cpu")
        except Exception:
            _PLACAS = False
    return _PLACAS or None


def motor_disponible() -> str:
    if _ocr_placas():
        return "Red OCR de placas (CCT)"
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


def candidatos_detalle(texto: str) -> list[tuple[str, str, int, int, str]]:
    """Placas colombianas posibles dentro del texto leído: (placa, tipo, costo, correcciones, patrón).
    Ej.: 'IGNP75F' -> GNP75F (moto). Así se descartan bordes, tornillos o letras de la ciudad.
    El formato antiguo de moto (ABC12) NO admite correcciones: con 5 caracteres, cambiar uno
    'inventa' una placa a partir de una lectura incompleta (caso MG650 -> MGG50)."""
    t = _limpiar(texto)
    res = []
    for tipo, patron in FORMATOS_CO:
        n = len(patron)
        for i in range(0, max(1, len(t) - n + 1)):
            cad = t[i:i + n]
            if len(cad) < n:
                continue
            placa, cambios = _ajustar(cad, patron)
            if not placa:
                continue
            if patron == "LLLDD" and cambios > 0:
                continue
            # penaliza correcciones, caracteres sobrantes y el formato antiguo de moto
            costo = cambios * 2 + (len(t) - n) + (2 if patron == "LLLDD" else 0)
            res.append((placa, tipo, costo, cambios, patron))
    return sorted(res, key=lambda r: r[2])


def candidatos_placa(texto: str) -> list[tuple[str, str, int]]:
    return [(p, t, c) for p, t, c, _, _ in candidatos_detalle(texto)]


def evaluar_lectura(bruto: str, final: str, confianza: float) -> dict:
    """¿La placa leída es confiable o hay que pedir confirmación al agente?"""
    from .config import MAX_CORRECCIONES_OCR, UMBRAL_CONFIANZA_OCR
    motivos = []
    det = next((c for c in candidatos_detalle(bruto) if c[0] == final), None)
    correcciones = det[3] if det else 0
    if not final:
        motivos.append("No se pudo leer la placa")
    elif det is None and len(final) < 6:
        motivos.append(f"Lectura incompleta: «{final}» no completa ningún formato de placa")
    elif det and det[4] == "LLLDD":
        motivos.append(f"Lectura de 5 caracteres («{final}»): puede faltar un carácter")
    if correcciones > MAX_CORRECCIONES_OCR:
        motivos.append(f"Se corrigieron {correcciones} caracteres de la lectura original «{_limpiar(bruto)}»")
    if final and confianza < UMBRAL_CONFIANZA_OCR:
        motivos.append(f"Confianza del OCR baja ({confianza:.0%}; mínimo {UMBRAL_CONFIANZA_OCR:.0%})")
    return {"correcciones": correcciones, "requiere_confirmacion": bool(motivos), "motivos": motivos}


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


def _confianza_tesseract(pytesseract, imagen, psm: int, texto: str) -> float:
    """Tesseract 5 reporta confianza 0 cuando se restringen los caracteres (whitelist).
    Se hace una segunda lectura sin restricción para obtener la confianza real, y solo se acepta
    si esa lectura coincide con la primera; si no coinciden, la lectura es dudosa (confianza baja)."""
    data = pytesseract.image_to_data(imagen, config=f"--oem 3 --psm {psm}", output_type=pytesseract.Output.DICT)
    palabras = [(str(w), float(c)) for w, c in zip(data["text"], data["conf"]) if str(w).strip() and float(c) >= 0]
    if not palabras or not _limpiar(texto):
        return 0.0
    libre = _limpiar("".join(w for w, _ in palabras))
    objetivo = _limpiar(texto)
    from .database import _distancia
    if _distancia(libre, objetivo) > 1:
        return 0.3   # las dos lecturas no coinciden: dudosa
    return float(np.mean([c for _, c in palabras]) / 100)


def leer_placa(recorte_bgr: np.ndarray, corregir: bool = True) -> dict:
    binaria = preparar_recorte(recorte_bgr)
    cajas, limpia = segmentar_caracteres(binaria)
    dos_lineas = _dos_lineas(cajas)
    entrada = limpia if cajas else binaria
    texto, conf, motor = "", 0.0, motor_disponible()

    red = _ocr_placas()
    lector = None if red else _easyocr()
    if red:
        try:
            pred = red.run(cv2.cvtColor(recorte_bgr, cv2.COLOR_BGR2RGB), return_confidence=True)[0]
            texto = pred.plate
            probs = [float(p) for p in pred.char_probs[:len(texto)]]
            conf = min(probs) if probs else 0.0   # el carácter más dudoso decide la confianza
        except Exception as e:  # pragma: no cover
            motor = f"error: {e}"
    elif lector:
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
            conf = _confianza_tesseract(pytesseract, entrada, psm, texto)
        except Exception as e:  # pragma: no cover
            motor = f"error: {e}"

    bruto = _limpiar(texto)
    final = corregir_formato_colombiano(bruto) if corregir else bruto
    calidad = evaluar_lectura(bruto, final, conf)
    return {"texto": final, "texto_bruto": bruto, "confianza": round(conf, 3), "motor": motor, "binaria": binaria,
            **calidad,
            "segmentada": entrada, "n_caracteres": len(cajas), "dos_lineas": dos_lineas}
