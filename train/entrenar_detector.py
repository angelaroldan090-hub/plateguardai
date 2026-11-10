"""Entrenamiento del detector de placas (YOLO) con las anotaciones COCO del Drive.

Uso:
    1) En la app, pestaña "Dataset": pulse "Exportar a formato YOLO" (crea data/yolo/data.yaml).
    2) pip install ultralytics
    3) python train/entrenar_detector.py --epocas 50
Salida: models/placas.pt (la app lo usa automáticamente en lugar del detector clásico).
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import DATA_DIR, MODELS_DIR  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_DIR / "yolo" / "data.yaml"))
    ap.add_argument("--epocas", type=int, default=50)
    ap.add_argument("--modelo", default="yolov8n.pt")
    ap.add_argument("--img", type=int, default=640)
    args = ap.parse_args()

    from ultralytics import YOLO

    modelo = YOLO(args.modelo)
    # Augmentación propia de YOLO ajustada a placas: sin volteo horizontal (fliplr=0)
    res = modelo.train(data=args.data, epochs=args.epocas, imgsz=args.img, fliplr=0.0,
                       degrees=8, perspective=0.0005, hsv_v=0.5, project=str(MODELS_DIR / "runs"), name="placas")
    mejor = Path(res.save_dir) / "weights" / "best.pt"
    shutil.copy(mejor, MODELS_DIR / "placas.pt")
    print("Detector guardado en", MODELS_DIR / "placas.pt")


if __name__ == "__main__":
    main()
