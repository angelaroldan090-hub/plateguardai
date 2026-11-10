# PlateGuardAI · Detección de placas y sistema de alertas vehiculares

Interfaz (Streamlit) del sistema que detecta la placa de un vehículo, la lee, la clasifica
(nacional/internacional × carro/moto) y cruza los registros (base local + **scraping** de
portales de tránsito) para emitir una alerta **antes** de que el agente se acerque.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-local.txt                    # versión completa (scraping + EasyOCR)
playwright install chromium                             # navegador para el scraping
# OCR: EasyOCR se instala con requirements. Alternativa liviana: instalar Tesseract
python tools/generar_demo.py                            # imágenes de prueba
streamlit run app.py
```

## Versión web con scraping

Para publicarla con un link (celular con cámara en vivo) y con scraping real, siga **DESPLIEGUE.md**:
app web en Streamlit Cloud + base de datos PostgreSQL en Supabase + nodo de scraping
(`nodo_scraping.py`) en su computador, que atiende las consultas que se piden desde la web.

## Uso desde el celular (red local)

La interfaz se adapta a pantallas pequeñas (menú lateral plegable, columnas apiladas).

1. Conecte el computador y el celular a la misma red Wi-Fi.
2. Ejecute `streamlit run app.py` y abra en el celular la dirección **Network URL** que muestra la terminal
   (por ejemplo `http://192.168.1.20:8501`).
3. Para tomar la foto use **Subir imagen**: en el celular ofrece la opción *Tomar foto* con la cámara nativa
   (mejor resolución que la vista previa del navegador).
4. La opción **Cámara** (vista en vivo) exige HTTPS fuera de `localhost`. Para usarla, publique la app con un
   túnel HTTPS (`cloudflared tunnel --url http://localhost:8501` o `ngrok http 8501`) o despliéguela en
   Streamlit Community Cloud.

## Dataset del profesor

Descargue la carpeta `reto_placas` del Drive y copie `set1`…`set4` en `data/reto_placas/`.
Cada set es una exportación COCO de Roboflow (`_annotations.coco.json` + imágenes); la app la lee sola.

## Módulos de la interfaz → etapas del reto

| Etapa del reto | Dónde está | Archivo |
|---|---|---|
| Recolección de datos (nacional, internacional, carro, moto + 5 categorías) | Dataset (estructura, etiquetado) | `core/dataset.py`, `core/config.py` |
| Preprocesamiento: CLAHE, normalización, augmentation de placas | Preprocesamiento | `core/preprocessing.py` |
| Detección de placa y extracción de la información | Verificación en campo | `core/detection.py`, `core/ocr.py` |
| Sistema de clasificación | Verificación → Clasificación | `core/classifier.py` |
| Entrenamiento y manejo de clases | Entrenamiento | `train/*.py`, `dataset.pesos_de_clase` |
| Consulta en BD, cruce de registros, alertas | Consulta / BD y scraping | `core/database.py`, `core/scraper.py`, `core/alerts.py` |

## Las 5 categorías de alerta (cubren los 6 criterios del reto)

| Categoría | Nivel | Criterio del reto |
|---|---|---|
| N0 · Normal | 0 | Sin alertas |
| MD1 · Deuda, multas o sanciones | 1 | Multas/sanciones pendientes (incl. inmovilización) |
| DV1 · Documentos vencidos | 1 | SOAT, técnico-mecánica |
| CL2 · Posible clonación | 2 | Clonación (reporte o inconsistencia imagen vs. registro) |
| AI3 · Acto ilegal | 3 | Eventos ilegales / uso en delitos / hurto |
| Pico y placa | flag | Se calcula aparte (Medellín 2º sem. 2026) |

## Scraping

`core/scraper.py` usa Playwright con un perfil de navegador persistente (`data/browser_profile`):

* **Movilidad Medellín**: el portal exige iniciar sesión. En *BD y scraping* pulse
  «Abrir portal para iniciar sesión», ingrese con su cuenta una vez y la sesión queda guardada.
* **SIMIT** y **RUNT**: pueden mostrar CAPTCHA; el scraper abre la ventana y una persona lo resuelve.
* Ingesta continua: el nodo refresca las placas en seguimiento cada 2 h como máximo; pausa entre consultas para no saturar los portales.
* El parser (`parsear_resultado`) es independiente del navegador y se prueba con `python tests/test_parser.py`.
  Si un portal cambia su HTML, ajuste las palabras clave de `PALABRAS` o el selector de espera.

## Modelos

Sin modelos entrenados la app ya funciona (detector clásico OpenCV + reglas). Al entrenar:

```bash
# En la app: Dataset → Exportar a formato YOLO / Exportar recortes balanceados
pip install ultralytics tensorflow
python train/entrenar_detector.py --epocas 50       # -> models/placas.pt
python train/entrenar_clasificador.py --epocas 30   # -> models/clasificador_placas.keras
```
La app detecta los archivos de `models/` y los usa automáticamente.

## Ley 1581 de 2012
Solo se guardan datos del vehículo, no del propietario; el historial puede seudonimizar la placa (hash).
Los registros iniciales de `data/plateguardai.db` son **sintéticos** (para probar las alertas).
