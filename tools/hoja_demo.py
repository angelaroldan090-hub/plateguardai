"""Genera data/demo/hoja_placas_demo.pdf: placas para la demostración en vivo con el celular.
Imprima la hoja (o muéstrela en otra pantalla) y apunte la cámara a una placa a la vez."""
import sys
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import DATA_DIR  # noqa: E402
from tools.generar_demo import placa  # noqa: E402

CASOS = [
    ("LUZ482", False, "N0 · Sin alertas"),
    ("KTM123", False, "MD1 · Multas pendientes"),
    ("HJK321", False, "DV1 · SOAT vencido"),
    ("EGX799", False, "CL2 · Posible clonación"),
    ("MNB654", False, "AI3 · Reportado por hurto"),
    ("ABC12D", True, "AI3 · Moto usada en delito"),
]


def fuente(t):
    for f in ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(f, t)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    W, H = 2480, 3508  # A4 a 300 dpi
    hoja = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(hoja)
    d.rectangle([0, 0, W, 230], fill=(11, 31, 75))
    d.text((140, 70), "PlateGuardAI · Placas de demostración", font=fuente(84), fill="white")
    d.text((140, 260), "Registros sintéticos de la base de prueba. Apunte la cámara a una placa a la vez.",
           font=fuente(44), fill=(95, 107, 122))
    celda_w, celda_h, y0 = W // 2, 1000, 400
    for i, (txt, moto, etiqueta) in enumerate(CASOS):
        img = placa(txt, moto)
        img = cv2.resize(img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        cx, cy = (i % 2) * celda_w + celda_w // 2, y0 + (i // 2) * celda_h
        hoja.paste(pil, (cx - pil.width // 2, cy + 40))
        d.text((cx - pil.width // 2, cy + 40 + pil.height + 30), etiqueta, font=fuente(46), fill=(26, 32, 44))
    destino = DATA_DIR / "demo" / "hoja_placas_demo.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino, resolution=300)
    hoja.resize((W // 4, H // 4)).save(destino.with_suffix(".png"))
    print("Hoja generada:", destino)


if __name__ == "__main__":
    main()
