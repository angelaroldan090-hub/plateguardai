"""PlateGuardAI · Sistema inteligente de detección de placas y alertas vehiculares.

Ejecutar:  streamlit run app.py
"""
import random
from pathlib import Path

import cv2
import pandas as pd
import streamlit as st

from core import classifier, database as db, dataset, detection, ocr, pipeline, preprocessing, scraper
from core.config import (MODO_NUBE, ANONIMIZAR_HISTORIAL_POR_DEFECTO, CATEGORIAS_ALERTA, CLASES_VEHICULO, DATA_DIR,
                         DATASET_DIR, MODELS_DIR, PICO_Y_PLACA)
from ui import auth, componentes as ui

st.set_page_config(page_title="PlateGuardAI · Verificación vehicular", page_icon=str(Path(__file__).parent / "assets" / "favicon.png"), layout="wide")
ui.estilos()
auth.requerir_login()
db.inicializar()
if not any(DATA_DIR.joinpath("demo").glob("*.jpg")):
    import subprocess, sys
    subprocess.run([sys.executable, str(Path(__file__).parent / "tools" / "generar_demo.py")], check=False)

DEMO_DIR = DATA_DIR / "demo"
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

# ---------------------------------------------------------------------------
# Barra lateral: navegación + configuración global
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(ui.logo_html(), unsafe_allow_html=True)
    st.markdown('<div class="seccion-lbl">Módulos</div>', unsafe_allow_html=True)
    pagina = st.radio("Módulo", [
        "Verificación en campo",
        "Consulta por placa",
        "Preprocesamiento",
        "Dataset",
        "Entrenamiento",
        "Base de datos y scraping",
        "Historial",
    ], label_visibility="collapsed")

    st.divider()
    st.markdown('<div class="seccion-lbl">Consulta en línea (scraping)</div>', unsafe_allow_html=True)
    fuentes_sel = st.multiselect(
        "Fuentes", list(scraper.FUENTES), default=["simit", "medellin"], placeholder="Seleccione fuentes",
        format_func=lambda f: scraper.FUENTES[f]["nombre"],
        help="Cada placa leída se consulta automáticamente en estas fuentes. Si no selecciona ninguna, solo se cruza con la base de datos del sistema.")
    if scraper.puede_scrapear_aqui():
        nav_visible = st.toggle("Mostrar navegador del scraper", value=True,
                                help="Necesario la primera vez (inicio de sesión) o si aparece un CAPTCHA.")
    else:
        nav_visible = False
        nodos = [n for n in db.estado_nodos() if n["en_linea"]]
        if nodos:
            st.caption(f"Nodo de scraping: en línea ({nodos[0]['nombre']}, hace {nodos[0]['hace_seg']} s). "
                       f"{(nodos[0].get('info') or '').split(';')[-1].strip().capitalize()}")
        else:
            st.caption("Nodo de scraping: desconectado. Las solicitudes quedan en cola hasta que se encienda "
                       "(python nodo_scraping.py en el computador).")
    anonimizar = st.toggle("Seudonimizar placas en el historial (Ley 1581)", value=ANONIMIZAR_HISTORIAL_POR_DEFECTO)

    with st.expander("Parámetros CLAHE"):
        clip = st.slider("Clip limit", 1.0, 6.0, 2.0, 0.5)
        tile = st.slider("Tamaño de rejilla", 2, 16, 8, 2)
        denoise = st.checkbox("Filtro bilateral (ruido)", True)

    st.divider()
    st.markdown('<div class="seccion-lbl">Estado de los motores</div>', unsafe_allow_html=True)
    st.caption(f"Detector: {detection.motor_disponible()}")
    st.caption(f"OCR: {ocr.motor_disponible()}")
    st.caption(f"Clasificador: {classifier.motor_disponible()}")
    st.caption("Scraping: " + ("directo (Playwright)" if scraper.puede_scrapear_aqui() else "vía nodo local"))
    st.caption(f"Base de datos: {db.descripcion_motor()}")
    auth.boton_salir()


def panel_fuentes(scraping: dict, key: str) -> bool:
    """Muestra el resultado de cada fuente en línea. Devuelve True si se pulsó «Actualizar»."""
    if not scraping:
        st.caption("No se consultaron fuentes en línea. Selecciónelas en la barra lateral.")
        return False
    for f, res in scraping.items():
        estado = "PENDIENTE" if res.pendiente and not res.datos else ("OK" if res.ok else "ERROR")
        with st.expander(f"[{estado}] {scraper.FUENTES[f]['nombre']} — {res.mensaje}", expanded=res.pendiente):
            if res.datos:
                d = res.datos
                if d.get("resumen"):
                    rs = d["resumen"]
                    st.write(f"Comparendos: {rs.get('comparendos', 0)} · Multas: {rs.get('multas', 0)} · "
                             f"Acuerdos de pago: {rs.get('acuerdos', 0)} · Total: ${rs.get('total', 0):,.0f}".replace(",", "."))
                if d.get("sin_novedad"):
                    st.success("Sin comparendos, multas ni pendientes en esta fuente.")
                if d.get("detalle"):
                    st.dataframe(pd.DataFrame(d["detalle"]), hide_index=True, use_container_width=True)
                for nota in d.get("informativo", []):
                    st.caption(f"Información: {nota}")
                with st.popover("Ver texto extraído de la página"):
                    st.text(d.get("texto_extraido", "")[:2000])
    if any(res.pendiente for res in scraping.values()):
        return st.button("Actualizar resultados en línea", key=key, use_container_width=True)
    return False


def mostrar_resultado(r: dict):
    """Panel de resultados de una verificación por imagen."""
    alerta, clasif = r["alerta"], r["clasificacion"]
    izq, der = st.columns([1.35, 1])
    with izq:
        st.image(ui.bgr2rgb(r["anotada"]), use_container_width=True, caption="Detección sobre la imagen preprocesada (CLAHE)")
    with der:
        if not r["detecciones"]:
            st.error("No se detectó ninguna placa. Pruebe con otra imagen, acerque la cámara o ajuste CLAHE.")
            return
        st.markdown(ui.placa_html(r["placa"], (clasif or {}).get("color_fondo"), (clasif or {}).get("naturaleza")),
                    unsafe_allow_html=True)
        lect = r["lecturas"][0]
        st.caption(f"OCR: {lect['motor']} · confianza de la lectura {lect['confianza']:.0%} · "
                   f"lectura original «{lect['texto_bruto']}»"
                   + (f" · {lect.get('correcciones', 0)} carácter(es) corregido(s)" if lect.get("correcciones") else ""))

        def _confirmar(placa_ok: str):
            res, scr = pipeline.consultar(placa_ok, clasif, fuentes_sel, nav_visible, anonimizar, origen="confirmada")
            r.update(placa=placa_ok, alerta=res, scraping=scr, sugerencias=[], requiere_confirmacion=False)
            st.rerun()

        if r.get("requiere_confirmacion"):
            # Lectura no confiable: NO se muestra ningún resultado hasta que el agente confirme la placa
            ui.tarjeta_confirmacion(r["placa"], r.get("motivos_confirmacion", []))
            opciones = list(dict.fromkeys(r.get("sugerencias", [])))
            for sug in opciones:
                if st.button(f"Es la placa {sug} (registrada)", key=f"sug_{sug}", use_container_width=True):
                    _confirmar(sug)
            if r["placa"] and st.button(f"Verifiqué la placa física: es {r['placa']}", key="conf_leida",
                                        use_container_width=True):
                _confirmar(r["placa"])
            st.caption("Si no es ninguna, escriba la placa correcta en «Corregir placa» y pulse Analizar vehículo.")
            return
        if r.get("sugerencias") and alerta and not alerta["registrado"]:
            st.warning(f"La placa {r['placa']} no está registrada. Si fue un error de lectura, confirme la correcta:")
            for sug in r["sugerencias"]:
                if st.button(f"Es la placa {sug}", key=f"sug_{sug}", use_container_width=True):
                    _confirmar(sug)
        if alerta:
            ui.tarjeta_alerta(alerta)
        else:
            st.warning("No se pudo leer el texto de la placa. Escríbalo en 'Corregir placa' para consultar.")

    if clasif:
        c = st.columns(4)
        with c[0]:
            ui.tarjeta("Naturaleza", clasif["naturaleza"].capitalize())
        with c[1]:
            ui.tarjeta("Tipo de vehículo", clasif["tipo"].capitalize())
        with c[2]:
            ui.tarjeta("Color de placa / servicio", f"{clasif['color_fondo']} · {clasif['servicio']}")
        with c[3]:
            ui.tarjeta("Tiempo total", f"{r['tiempos']['total'] * 1000:.0f} ms")

    t1, t2, t3, t4 = st.tabs(["Hallazgos", "Etapas del pipeline", "Clasificación", "Fuentes en línea"])
    with t1:
        if alerta:
            ui.ficha_vehiculo(alerta.get("vehiculo"))
            st.write("")
            ui.hallazgos_tabla(alerta)
    with t2:
        d0, l0 = r["detecciones"][0], r["lecturas"][0]
        cols = st.columns(5)
        pasos = [(r["etapas"]["original"], "1 · Original"), (r["etapas"]["clahe"], "2 · CLAHE"),
                 (d0.recorte, "3 · Placa detectada"), (l0["binaria"], "4 · Binarización (Otsu)"),
                 (l0["segmentada"], f"5 · Segmentación ({l0['n_caracteres']} caracteres)")]
        for col, (img, nombre) in zip(cols, pasos):
            with col:
                st.image(ui.bgr2rgb(img), use_container_width=True)
                st.markdown(f'<div class="paso">{nombre}</div>', unsafe_allow_html=True)
        st.write("")
        st.bar_chart(pd.DataFrame({"ms": {k: v * 1000 for k, v in r["tiempos"].items() if k != "total"}}),
                     horizontal=True, height=220, color="#0A66FF")
    with t3:
        if clasif:
            st.caption(f"Motor: {clasif['motor']}")
            st.bar_chart(pd.DataFrame({"probabilidad": clasif["probabilidades"]}), height=240, color="#0A66FF")
    with t4:
        if panel_fuentes(r["scraping"], key="act_img"):
            res, scr = pipeline.consultar(r["placa"], clasif, list(r["scraping"]), nav_visible, anonimizar,
                                          origen="actualización")
            r.update(alerta=res, scraping=scr)
            st.rerun()


# ---------------------------------------------------------------------------
# 1. Verificación en campo
# ---------------------------------------------------------------------------
if pagina == "Verificación en campo":
    ui.encabezado("Verificación en campo")
    st.caption("Capture o cargue la imagen del vehículo. El sistema detecta la placa, la lee, la clasifica "
               "y cruza los registros para emitir la alerta antes de que el agente se acerque.")

    modo = st.segmented_control("Fuente de la imagen", ["Cámara", "Subir imagen", "Imagen de prueba", "Del dataset"],
                                default="Subir imagen")
    img = None
    if modo == "Cámara":
        img = ui.leer_subida(st.camera_input("Apunte a la placa del vehículo"))
    elif modo == "Subir imagen":
        img = ui.leer_subida(st.file_uploader("Imagen del vehículo", type=["jpg", "jpeg", "png", "webp"]))
    elif modo == "Imagen de prueba":
        demos = sorted(DEMO_DIR.glob("*.jpg"))
        if not demos:
            st.info("Genere imágenes de prueba con: python tools/generar_demo.py")
        else:
            sel = st.selectbox("Imagen", demos, format_func=lambda p: p.stem.replace("demo_", "Escena sintética "))
            img = cv2.imread(str(sel))
    else:
        df = dataset.cargar()
        if df.empty:
            st.info(f"No se encontró el dataset en {DATASET_DIR}. Descargue la carpeta del Drive (set1…set4) allí.")
        else:
            rutas = sorted(df["ruta"].unique())
            sel = st.selectbox("Imagen del dataset", rutas, format_func=lambda p: "/".join(Path(p).parts[-2:]))
            img = cv2.imread(sel)

    # Formulario con botón propio: en el celular no hay que pulsar «Enter» para enviar la placa
    with st.form("form_correccion", border=False):
        corregir = st.text_input("Corregir placa (opcional)", placeholder="Si el OCR se equivoca, escriba la placa aquí",
                                 max_chars=8).upper().replace(" ", "").replace("-", "")
        usar_placa = st.form_submit_button("Usar esta placa", use_container_width=True)
    if usar_placa and corregir and img is None:
        st.info("Cargue la imagen del vehículo y pulse «Analizar vehículo», o use el módulo «Consulta por placa».")

    if img is not None:
        if st.button("Analizar vehículo", type="primary", use_container_width=True) or (usar_placa and corregir):
            with st.spinner("Procesando imagen y consultando SIMIT / Movilidad Medellín…"):
                st.session_state["ultimo"] = pipeline.procesar_imagen(
                    img, clip, tile, denoise, fuentes_sel, nav_visible, corregir or None, anonimizar, origen=modo)
        if "ultimo" in st.session_state:
            mostrar_resultado(st.session_state["ultimo"])

# ---------------------------------------------------------------------------
# 2. Consulta por placa
# ---------------------------------------------------------------------------
elif pagina == "Consulta por placa":
    ui.encabezado("Consulta por placa")
    st.caption("Consulta directa cuando no hay imagen (p. ej. reporte por radio).")
    # Formulario con botón: funciona en el celular sin la tecla «Enter»
    with st.form("form_consulta", border=False):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        with c1:
            placa = st.text_input("Placa", placeholder="ABC123 · ABC12D · PCD7841", max_chars=8).upper().replace(" ", "").replace("-", "")
        with c2:
            buscar = st.form_submit_button("Consultar", type="primary", use_container_width=True)
    st.caption("Placas de ejemplo en la base local: " + " · ".join(db.tabla("vehiculos")["placa"].tolist()))
    if buscar and placa:
        with st.spinner("Cruzando registros…"):
            st.session_state["consulta"] = (placa, *pipeline.consultar(placa, None, fuentes_sel, nav_visible,
                                                                        anonimizar, origen="manual"))
    if "consulta" in st.session_state:
        placa, res, scr = st.session_state["consulta"]
        izq, der = st.columns([1, 1.6])
        with izq:
            st.markdown(ui.placa_html(placa), unsafe_allow_html=True)
            st.write("")
            ui.tarjeta_alerta(res)
        with der:
            ui.ficha_vehiculo(res.get("vehiculo"))
            st.write("")
            ui.hallazgos_tabla(res)
            if scr and panel_fuentes(scr, key="act_manual"):
                st.session_state["consulta"] = (placa, *pipeline.consultar(placa, None, list(scr), nav_visible,
                                                                            anonimizar, origen="actualización"))
                st.rerun()

# ---------------------------------------------------------------------------
# 3. Preprocesamiento
# ---------------------------------------------------------------------------
elif pagina == "Preprocesamiento":
    ui.encabezado("Preprocesamiento")
    st.caption("Limpieza con CLAHE, normalización y data augmentation específico para placas.")
    arch = st.file_uploader("Imagen", type=["jpg", "jpeg", "png"])
    img = ui.leer_subida(arch)
    if img is None:
        demos = sorted(DEMO_DIR.glob("*.jpg"))
        if demos:
            img = cv2.imread(str(demos[0]))
            st.caption("Usando una imagen de prueba. Suba la suya para comparar.")
    if img is not None:
        et = preprocessing.preprocesar(img, clip, tile, denoise)
        t1, t2, t3 = st.tabs(["Limpieza (CLAHE)", "Normalización", "Data augmentation"])
        with t1:
            a, b = st.columns(2)
            a.image(ui.bgr2rgb(et["original"]), caption="Original", use_container_width=True)
            b.image(ui.bgr2rgb(et["clahe"]), caption=f"CLAHE (clip={clip}, rejilla={tile}×{tile})", use_container_width=True)
            h = pd.DataFrame({"original": preprocessing.histograma(et["original"]),
                              "CLAHE": preprocessing.histograma(et["clahe"])})
            st.markdown("**Histograma de intensidad** (CLAHE redistribuye el contraste por regiones sin saturar)")
            st.line_chart(h, height=220)
        with t2:
            modo = st.radio("Método", ["minmax", "zscore"], horizontal=True,
                            format_func=lambda m: "Min-Max [0,1]" if m == "minmax" else "Z-score (μ=0, σ=1)")
            x = preprocessing.normalizar(et["clahe"], (224, 224), modo)
            a, b = st.columns([1, 1])
            a.image(ui.bgr2rgb(preprocessing.a_visible(x)), caption="Tensor 224×224×3 (visualizado)", width=320)
            with b:
                ui.tarjeta("Forma", str(x.shape))
                st.write("")
                ui.tarjeta("Media / desviación", f"{x.mean():.3f} / {x.std():.3f}")
                st.write("")
                ui.tarjeta("Mín / máx", f"{x.min():.3f} / {x.max():.3f}")
        with t3:
            dets = detection.detectar_placas(et["clahe"])
            base = dets[0].recorte if dets else et["clahe"]
            st.caption("Se aplica sobre el recorte de la placa. **No** se usa volteo horizontal: invertiría los "
                       "caracteres y generaría placas que no existen.")
            if st.button("Regenerar muestras"):
                random.seed()
            nombres = list(preprocessing.AUGMENTACIONES)
            filas = [nombres[i:i + 3] for i in range(0, len(nombres), 3)]
            for fila in filas:
                cols = st.columns(3)
                for col, n in zip(cols, fila):
                    col.image(ui.bgr2rgb(preprocessing.AUGMENTACIONES[n](base)), caption=n, use_container_width=True)

# ---------------------------------------------------------------------------
# 4. Dataset
# ---------------------------------------------------------------------------
elif pagina == "Dataset":
    ui.encabezado("Dataset")
    st.caption(f"Imágenes del profesor (Drive `reto_placas`, formato COCO de Roboflow). Carpeta esperada: `{DATASET_DIR}`")
    df = dataset.cargar()
    if df.empty:
        st.warning("No se encontraron anotaciones COCO. Descargue `set1`, `set2`, `set3` y `set4` del Drive y "
                   f"cópielos en `{DATASET_DIR}` (cada uno con su `_annotations.coco.json`).")
        st.code("data/reto_placas/\n├── set1/_annotations.coco.json + imágenes\n├── set2/...\n├── set3/...\n└── set4/...")
    else:
        anot = df.dropna(subset=["x"])
        etiquetas = dataset.cargar_etiquetas()
        c = st.columns(4)
        with c[0]:
            ui.tarjeta("Imágenes", df["ruta"].nunique())
        with c[1]:
            ui.tarjeta("Placas anotadas", len(anot))
        with c[2]:
            ui.tarjeta("Sets", df["set"].nunique())
        with c[3]:
            ui.tarjeta("Etiquetadas por clase", f"{sum(1 for i in anot['id'] if i in etiquetas)} / {len(anot)}")

        t1, t2, t3 = st.tabs(["Estructura", "Etiquetado de clases", "Exportar"])
        with t1:
            a, b = st.columns(2)
            with a:
                st.markdown("**Anotaciones por set y categoría COCO**")
                st.dataframe(df.pivot_table(index="set", columns="categoria_coco", values="archivo", aggfunc="count", fill_value=0),
                             use_container_width=True)
            with b:
                st.markdown("**Relación de aspecto de las placas** (carro ≈ 2, moto ≈ 1.3)")
                st.bar_chart(anot["aspecto"].round(1).value_counts().sort_index(), height=250, color="#0A66FF")
            conteo = {c_: sum(1 for v in etiquetas.values() if v == c_) for c_ in CLASES_VEHICULO}
            st.markdown("**Distribución de clases** (nacional / internacional × carro / moto)")
            if sum(conteo.values()):
                st.bar_chart(pd.Series(conteo), height=220, color="#0A66FF")
            else:
                st.info("Aún no hay placas etiquetadas por clase. Use la pestaña 'Etiquetado de clases'.")
        with t2:
            st.caption("Revise la clase de cada placa. 'Autoetiquetar' propone la clase con OCR + formato + geometría; "
                       "luego corrija a mano lo que esté mal.")
            col_a, col_b, col_c = st.columns([1, 1, 2])
            sets = ["Todos"] + sorted(df["set"].unique())
            filtro = col_a.selectbox("Set", sets)
            solo_pend = col_b.checkbox("Solo sin etiquetar", True)
            sub = anot if filtro == "Todos" else anot[anot["set"] == filtro]
            if solo_pend:
                sub = sub[~sub["id"].isin(etiquetas)]
            if col_c.button(f"Autoetiquetar {min(len(sub), 60)} placas"):
                nuevas, prog = {}, st.progress(0.0)
                for i, (_, f) in enumerate(sub.head(60).iterrows()):
                    rec = dataset.recortar(f)
                    if rec is not None and rec.size:
                        txt = ocr.leer_placa(preprocessing.aplicar_clahe(rec))["texto"]
                        nuevas[f["id"]] = classifier.clasificar(txt, rec)["clase"]
                    prog.progress((i + 1) / min(len(sub), 60))
                dataset.guardar_etiquetas(nuevas)
                st.rerun()
            pagina_n = st.number_input("Página", 1, max(1, (len(sub) - 1) // 12 + 1), 1)
            bloque = sub.iloc[(pagina_n - 1) * 12: pagina_n * 12]
            cols = st.columns(4)
            for i, (_, f) in enumerate(bloque.iterrows()):
                with cols[i % 4]:
                    rec = dataset.recortar(f)
                    if rec is not None and rec.size:
                        st.image(ui.bgr2rgb(rec), use_container_width=True, caption=f"{f['set']} · {f['archivo'][:22]}…")
                    actual = etiquetas.get(f["id"])
                    sel = st.selectbox("Clase", ["(sin etiqueta)"] + CLASES_VEHICULO,
                                       index=(CLASES_VEHICULO.index(actual) + 1) if actual in CLASES_VEHICULO else 0,
                                       key=f"lbl_{f['id']}", label_visibility="collapsed")
                    if sel != "(sin etiqueta)" and sel != actual:
                        dataset.guardar_etiqueta(f["id"], sel)
        with t3:
            a, b = st.columns(2)
            with a:
                st.markdown("**Detector (YOLO)**")
                st.caption("Convierte las cajas COCO a formato YOLO (clase única «placa»), 80/20 train/val.")
                if st.button("Exportar a formato YOLO"):
                    ruta = dataset.exportar_yolo(df, DATA_DIR / "yolo")
                    st.success(f"Listo: {ruta}")
                st.code("python train/entrenar_detector.py --epocas 50")
            with b:
                st.markdown("**Clasificador (CNN)**")
                objetivo = st.number_input("Imágenes objetivo por clase (balanceo con augmentation)", 50, 3000, 300, 50)
                if st.button("Exportar recortes balanceados"):
                    with st.spinner("Recortando y aumentando…"):
                        cont = dataset.exportar_recortes(df, etiquetas, DATA_DIR / "recortes", objetivo)
                    st.success(f"Listo: {cont}")
                st.code("python train/entrenar_clasificador.py --epocas 30")

# ---------------------------------------------------------------------------
# 5. Entrenamiento
# ---------------------------------------------------------------------------
elif pagina == "Entrenamiento":
    ui.encabezado("Entrenamiento y manejo de clases")
    import json
    _mc = MODELS_DIR / "metricas_clasificador.json"
    if _mc.exists():
        conteo = json.loads(_mc.read_text())["conteos"]
    else:
        etiquetas = dataset.cargar_etiquetas()
        conteo = {c: sum(1 for v in etiquetas.values() if v == c) for c in CLASES_VEHICULO}
    pesos = dataset.pesos_de_clase(conteo)
    a, b = st.columns(2)
    with a:
        st.markdown("**Clases y pesos** (pesos = N / (k · nᵢ), compensan el desbalance)")
        st.dataframe(pd.DataFrame({"muestras": conteo, "peso": pesos}), use_container_width=True)
        st.caption("La clase minoritaria (motos) se amplía además con data augmentation específico para placas.")
    with b:
        st.markdown("**Arquitectura de los modelos**")
        st.code("Detector: YOLOv8n (CNN, 3,0 M parámetros)\n"
                "  entrada 512×512 · clase única «placa» · sin volteo horizontal\n"
                "Clasificador: YOLOv8n-cls (CNN, 1,4 M parámetros)\n"
                "  entrada 128×128 · 3 clases: nacional_carro, nacional_moto,\n"
                "  internacional_carro\n"
                "Ambos exportados a ONNX (OpenCV DNN, sin PyTorch en producción)", language="text")
    import json
    md, mc = MODELS_DIR / "metricas_detector.json", MODELS_DIR / "metricas_clasificador.json"
    if md.exists():
        m = json.loads(md.read_text())
        st.markdown(f"**Detector de placas** · {m['modelo']} · "
                    f"{m['imagenes']['entrenamiento']} imágenes de entrenamiento, {m['imagenes']['validacion']} de validación, "
                    f"{m['imagenes']['prueba']} de prueba (no vistas)")
        c = st.columns(4)
        for col, (k, v) in zip(c, m["final"].items()):
            with col:
                ui.tarjeta(k, f"{v:.3f}")
        st.write("")
        a1, a2 = st.columns(2)
        h = m["historial"]
        a1.line_chart(pd.DataFrame({k: h[k] for k in ("mAP50", "mAP50-95", "precision", "recall")}), height=230)
        a1.caption("Métricas de validación por época")
        filas = []
        for clave in ("comparacion_validacion", "comparacion_validacion_tesseract"):
            comp = m.get(clave)
            if not comp:
                continue
            motor = comp.get("motor_ocr", "")
            for nombre, k in (("Detector clásico", "clasico"), ("YOLO entrenado", "yolo")):
                filas.append({"OCR": motor, "Detector": nombre,
                              "Encuentra la placa": f"{comp[k]['encuentra_placa']:.1%}",
                              "Lee un formato válido": f"{comp[k]['lectura_valida']:.1%}",
                              "Segundos por imagen": f"{comp[k]['seg_imagen']} s"})
        a2.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
        a2.caption("Comparación sobre las 105 imágenes reales de validación")
    if mc.exists():
        m = json.loads(mc.read_text())
        st.divider()
        st.markdown(f"**Clasificador de placas** · {m['modelo']}")
        a1, a2 = st.columns(2)
        with a1:
            st.markdown("Manejo de clases (desbalance)")
            st.dataframe(pd.DataFrame({"Muestras originales": m["conteos"], "Tras data augmentation": m.get("conteos_tras_augmentation", m["conteos"])}),
                         use_container_width=True)
        with a2:
            st.markdown("Matriz de confusión (validación)")
            st.dataframe(pd.DataFrame(m["matriz_confusion"], index=m["clases"], columns=m["clases"]), use_container_width=True)
        st.line_chart(pd.DataFrame({k: v for k, v in m["historial"].items()}), height=200)
    if not md.exists() and not mc.exists():
        st.info("Aún no hay modelos entrenados. Siga los pasos de la pestaña Dataset → Exportar y luego ejecute "
                "los scripts de `train/`. Mientras tanto el sistema clasifica con reglas (formato + geometría + color).")

# ---------------------------------------------------------------------------
# 6. Base de datos y scraping
# ---------------------------------------------------------------------------
elif pagina == "Base de datos y scraping":
    ui.encabezado("Base de datos y scraping")
    t1, t2, t3 = st.tabs(["Fuentes en línea (scraping)", "Registros locales", "Agregar registro"])
    with t1:
        st.caption("El scraping abre un navegador (Playwright) con un perfil propio que conserva la sesión. "
                   "Los inicios de sesión y CAPTCHAs los resuelve una persona en esa ventana; el sistema no los evade.")
        st.dataframe(pd.DataFrame([{"Fuente": v["nombre"], "URL de consulta": v["url"], "Intervención humana": v["requiere_humano"]}
                                   for v in scraper.FUENTES.values()]), hide_index=True, use_container_width=True)
        nodos = db.estado_nodos()
        a, b = st.columns([1, 1.4])
        with a:
            st.markdown("**Nodos de scraping**")
            if nodos:
                st.dataframe(pd.DataFrame([{"Nodo": n["nombre"], "Estado": "En línea" if n["en_linea"] else "Desconectado",
                                            "Último latido": f"hace {n['hace_seg']} s"} for n in nodos]),
                             hide_index=True, use_container_width=True)
            else:
                st.caption("Ningún nodo se ha conectado todavía.")
            if not scraper.puede_scrapear_aqui():
                st.caption("Esta instancia (web) no ejecuta scraping: deja las solicitudes en cola y el nodo del "
                           "computador local las atiende (python nodo_scraping.py).")
            with st.form("solicitud"):
                st.markdown("**Solicitar consulta en línea**")
                sp = st.text_input("Placa").upper().replace(" ", "")
                sf = st.multiselect("Fuentes", ["simit", "medellin"], default=["simit", "medellin"],
                                    format_func=lambda k: scraper.FUENTES[k]["nombre"])
                if st.form_submit_button("Enviar a la cola") and sp:
                    for f_ in sf:
                        db.crear_solicitud(sp, f_)
                    st.success(f"Solicitud registrada para {sp}.")
        with b:
            st.markdown("**Cola de solicitudes**")
            sol = db.tabla("solicitudes")
            if sol.empty:
                st.caption("Sin solicitudes.")
            else:
                st.dataframe(sol.sort_values("id", ascending=False).head(30), hide_index=True, use_container_width=True)
            if st.button("Refrescar"):
                st.rerun()
        st.divider()
        st.markdown("**Ingesta continua** · el nodo refresca las placas en seguimiento cada 2 horas como máximo")
        ing = db.ultimas_ingestas(10)
        seg = db.lista_seguimiento()
        c = st.columns(4)
        with c[0]:
            ui.tarjeta("Placas en seguimiento", len(seg))
        with c[1]:
            ui.tarjeta("Última ingesta", ing.iloc[0]["inicio"] if not ing.empty else "—")
        with c[2]:
            ui.tarjeta("Estado", ing.iloc[0]["estado"] if not ing.empty else "Sin ingestas")
        with c[3]:
            pend = len(db.pendientes_de_ingesta(2))
            ui.tarjeta("Consultas desactualizadas (>2 h)", pend)
        st.write("")
        a, b = st.columns([1, 1.4])
        with a:
            with st.form("seguir", clear_on_submit=True):
                st.markdown("Agregar placa al seguimiento")
                sp = st.text_input("Placa", key="seg_placa").upper().replace(" ", "").replace("-", "")
                sf = st.multiselect("Fuentes", ["simit", "medellin"], default=["simit", "medellin"], key="seg_f",
                                    format_func=lambda k: scraper.FUENTES[k]["nombre"])
                motivo = st.text_input("Motivo / autorización", placeholder="Ej.: vehículo propio, flota autorizada")
                if st.form_submit_button("Agregar") and sp:
                    db.agregar_seguimiento(sp, ",".join(sf), motivo)
                    st.success(f"{sp} agregada. Se consultará en la próxima ingesta.")
            st.caption("Ley 1581 de 2012: agregue solo placas cuyo seguimiento esté autorizado.")
            if seg:
                quitar = st.selectbox("Quitar del seguimiento", ["—"] + [x["placa"] for x in seg])
                if quitar != "—" and st.button("Quitar"):
                    db.quitar_seguimiento(quitar)
                    st.rerun()
        with b:
            if seg:
                st.dataframe(pd.DataFrame(seg)[["placa", "fuentes", "motivo"]], hide_index=True, use_container_width=True)
            st.markdown("Historial de ingestas")
            if ing.empty:
                st.caption("El nodo aún no ha ejecutado ingestas. Encienda el nodo: python nodo_scraping.py")
            else:
                st.dataframe(ing[["id", "nodo", "inicio", "fin", "placas", "consultas_ok", "consultas_error", "estado"]],
                             hide_index=True, use_container_width=True)
        st.divider()
        if scraper.puede_scrapear_aqui():
            a, b = st.columns(2)
            with a:
                st.markdown("**1 · Iniciar sesión en el portal de Medellín** (una sola vez)")
                espera = st.slider("Tiempo para iniciar sesión (s)", 60, 600, 180, 30)
                if st.button("Abrir portal para iniciar sesión"):
                    with st.spinner("Inicie sesión en la ventana que se abrió…"):
                        st.success(scraper.abrir_para_login("medellin", espera))
            with b:
                st.markdown("**2 · Probar la consulta**")
                p = st.text_input("Placa de prueba", "EGX799").upper()
                f = st.selectbox("Fuente", list(scraper.FUENTES), format_func=lambda k: scraper.FUENTES[k]["nombre"])
                cache = st.checkbox("Usar resultado vigente (2 h)", True)
                if st.button("Ejecutar scraping", type="primary"):
                    with st.spinner("Consultando…"):
                        r = scraper.consultar_fuente(p, f, visible=nav_visible, usar_cache=cache)
                    (st.success if r.ok else st.error)(r.mensaje)
                    if r.datos:
                        st.json({k: v for k, v in r.datos.items() if k != "texto_extraido"})
                        with st.expander("Texto extraído de la página"):
                            st.text(r.datos.get("texto_extraido", ""))
    with t2:
        tabla = st.selectbox("Tabla", ["vehiculos", "documentos", "multas", "reportes", "cache_scraping", "solicitudes", "seguimiento", "ingestas", "consultas"])
        st.dataframe(db.tabla(tabla), hide_index=True, use_container_width=True)
        st.caption("Los registros iniciales son sintéticos y sirven para probar las 5 categorías de alerta.")
    with t3:
        tipo_reg = st.radio("Tipo de registro", ["Vehículo", "Documento", "Multa", "Reporte"], horizontal=True)
        with st.form("nuevo", clear_on_submit=True):
            placa = st.text_input("Placa").upper().replace(" ", "")
            if tipo_reg == "Vehículo":
                c = st.columns(3)
                nat = c[0].selectbox("Naturaleza", ["nacional", "internacional"])
                tipo = c[1].selectbox("Tipo", ["carro", "moto"])
                serv = c[2].selectbox("Servicio", ["Particular", "Servicio público", "Diplomático", "Oficial"])
                c = st.columns(5)
                datos = dict(placa=placa, naturaleza=nat, tipo=tipo, servicio=serv, marca=c[0].text_input("Marca"),
                             linea=c[1].text_input("Línea"), modelo=c[2].number_input("Modelo", 1950, 2030, 2020),
                             color=c[3].text_input("Color"), ciudad=c[4].text_input("Ciudad"))
            elif tipo_reg == "Documento":
                datos = dict(placa=placa, documento=st.selectbox("Documento", ["SOAT", "Revisión técnico-mecánica"]),
                             vence=str(st.date_input("Vence")))
            elif tipo_reg == "Multa":
                datos = dict(placa=placa, codigo=st.text_input("Código"), descripcion=st.text_input("Descripción"),
                             valor=st.number_input("Valor", 0, 100_000_000, 604200, 1000), fecha=str(st.date_input("Fecha")),
                             estado=st.selectbox("Estado", ["Pendiente", "Pagada"]), inmoviliza=int(st.checkbox("Exige inmovilización")))
            else:
                datos = dict(placa=placa, tipo=st.selectbox("Tipo", ["hurto", "delito", "evento_ilegal", "clonacion"]),
                             descripcion=st.text_input("Descripción"), fecha=str(st.date_input("Fecha")),
                             fuente=st.text_input("Fuente", "Registro manual"), activo=1)
            if st.form_submit_button("Guardar", type="primary") and placa:
                if tipo_reg == "Vehículo":
                    db.guardar_vehiculo(datos)
                else:
                    db.agregar({"Documento": "documentos", "Multa": "multas", "Reporte": "reportes"}[tipo_reg], datos)
                st.success(f"{tipo_reg} guardado para {placa}.")

# ---------------------------------------------------------------------------
# 7. Historial
# ---------------------------------------------------------------------------
else:
    ui.encabezado("Historial de consultas")
    h = db.historial()
    if h.empty:
        st.info("Aún no hay consultas.")
    else:
        c = st.columns(4)
        with c[0]:
            ui.tarjeta("Consultas", len(h))
        with c[1]:
            ui.tarjeta("Con alerta", int((h["nivel"] > 0).sum()))
        with c[2]:
            ui.tarjeta("Riesgo alto", int((h["nivel"] >= 3).sum()))
        with c[3]:
            ui.tarjeta("Tasa de alerta", f"{(h['nivel'] > 0).mean():.0%}")
        st.write("")
        a, b = st.columns([1, 2])
        with a:
            st.markdown("**Por categoría**")
            cat = h["categoria"].map(lambda k: CATEGORIAS_ALERTA[k]["titulo"]).value_counts()
            st.bar_chart(cat, horizontal=True, height=260, color="#0A66FF")
        with b:
            st.markdown("**Registro**")
            h2 = h.copy()
            h2["categoria"] = h2["categoria"].map(lambda k: f"{CATEGORIAS_ALERTA[k]['codigo']} · {CATEGORIAS_ALERTA[k]['titulo']}")
            st.dataframe(h2.drop(columns=["id"]), hide_index=True, use_container_width=True, height=300)
        st.download_button("Descargar CSV", h.to_csv(index=False).encode(), "historial_plateguardai.csv", "text/csv")
    st.caption("Ley 1581 de 2012 (protección de datos personales): el sistema solo guarda datos del vehículo, "
               "permite seudonimizar la placa en el historial y no extrae datos del propietario de los portales.")

st.sidebar.caption(f"Pico y placa {PICO_Y_PLACA['ciudad']} ({PICO_Y_PLACA['vigencia']}): "
                   + " · ".join(f"{DIAS[d][:2]} {'-'.join(map(str, v))}" for d, v in PICO_Y_PLACA["dias"].items()))
ui.pie()
