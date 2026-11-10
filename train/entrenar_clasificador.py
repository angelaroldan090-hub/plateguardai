"""Entrenamiento de la CNN de clasificación (nacional/internacional x carro/moto).

Uso:
    1) En la app, pestaña "Dataset": etiquete las placas y pulse "Exportar recortes balanceados".
       Eso crea data/recortes/<clase>/*.jpg (con CLAHE + data augmentation).
    2) python train/entrenar_clasificador.py --epocas 30
Salida: models/clasificador_placas.keras y models/metricas_clasificador.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import CLASES_VEHICULO, DATA_DIR, MODELS_DIR  # noqa: E402


def construir_cnn(n_clases, entrada=(64, 128, 3)):
    import tensorflow as tf
    from tensorflow.keras import layers, models

    m = models.Sequential([
        layers.Input(shape=entrada),
        layers.Conv2D(32, 3, padding="same", activation="relu"), layers.BatchNormalization(), layers.MaxPooling2D(),
        layers.Conv2D(64, 3, padding="same", activation="relu"), layers.BatchNormalization(), layers.MaxPooling2D(),
        layers.Conv2D(128, 3, padding="same", activation="relu"), layers.BatchNormalization(), layers.MaxPooling2D(),
        layers.Conv2D(128, 3, padding="same", activation="relu"), layers.GlobalAveragePooling2D(),
        layers.Dropout(0.4),
        layers.Dense(128, activation="relu"),
        layers.Dense(n_clases, activation="softmax"),
    ])
    m.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default=str(DATA_DIR / "recortes"))
    ap.add_argument("--epocas", type=int, default=30)
    ap.add_argument("--lote", type=int, default=32)
    args = ap.parse_args()

    import tensorflow as tf

    ds_args = dict(directory=args.datos, image_size=(64, 128), batch_size=args.lote, label_mode="int",
                   class_names=CLASES_VEHICULO, validation_split=0.2, seed=42)
    train = tf.keras.utils.image_dataset_from_directory(subset="training", **ds_args)
    val = tf.keras.utils.image_dataset_from_directory(subset="validation", **ds_args)
    norm = lambda x, y: (x / 255.0, y)  # noqa: E731  (normalización min-max)
    train, val = train.map(norm).prefetch(2), val.map(norm).prefetch(2)

    # Manejo de clases: pesos inversos a la frecuencia
    conteos = {i: len(list((Path(args.datos) / c).glob("*.jpg"))) for i, c in enumerate(CLASES_VEHICULO)}
    total, n = sum(conteos.values()), sum(1 for v in conteos.values() if v)
    pesos = {i: (total / (n * v) if v else 0.0) for i, v in conteos.items()}

    modelo = construir_cnn(len(CLASES_VEHICULO))
    cb = [tf.keras.callbacks.EarlyStopping(patience=6, restore_best_weights=True),
          tf.keras.callbacks.ReduceLROnPlateau(patience=3, factor=0.5)]
    hist = modelo.fit(train, validation_data=val, epochs=args.epocas, class_weight=pesos, callbacks=cb)

    y_true, y_pred = [], []
    for x, y in val:
        y_true += list(y.numpy())
        y_pred += list(np.argmax(modelo.predict(x, verbose=0), axis=1))
    cm = tf.math.confusion_matrix(y_true, y_pred, num_classes=len(CLASES_VEHICULO)).numpy().tolist()

    MODELS_DIR.mkdir(exist_ok=True)
    modelo.save(MODELS_DIR / "clasificador_placas.keras")
    (MODELS_DIR / "metricas_clasificador.json").write_text(json.dumps({
        "historial": {k: [float(v) for v in vs] for k, vs in hist.history.items()},
        "matriz_confusion": cm, "clases": CLASES_VEHICULO,
        "conteos": {CLASES_VEHICULO[i]: v for i, v in conteos.items()},
        "pesos_clase": {CLASES_VEHICULO[i]: round(p, 3) for i, p in pesos.items()},
    }, indent=2))
    print("Modelo guardado en", MODELS_DIR / "clasificador_placas.keras")


if __name__ == "__main__":
    main()
