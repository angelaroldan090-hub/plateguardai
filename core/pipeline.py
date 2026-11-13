"""Orquestador: imagen -> preprocesamiento -> detección -> OCR -> clasificación -> cruce -> alerta."""
from __future__ import annotations

import time

from . import alerts, classifier, database as db, detection, ocr, preprocessing, scraper


def procesar_imagen(img_bgr, clip_limit=2.0, tile=8, denoise=True, fuentes_scraping=None,
                    navegador_visible=True, placa_manual: str | None = None, anonimizar=True, origen="imagen"):
    t0 = time.perf_counter()
    tiempos = {}

    etapas = preprocessing.preprocesar(img_bgr, clip_limit, tile, denoise)
    tiempos["preprocesamiento"] = time.perf_counter() - t0

    t = time.perf_counter()
    base = etapas["clahe"]
    dets = detection.detectar_placas(base)
    tiempos["detección"] = time.perf_counter() - t

    t = time.perf_counter()
    # La red OCR de placas lee mejor la foto original (con toda su resolución) que la versión con CLAHE
    lecturas = [ocr.leer_placa(_recorte_original(img_bgr, base, d)) for d in dets]
    tiempos["OCR"] = time.perf_counter() - t

    # Se elige el candidato cuya lectura tiene formato de placa (no el de mayor puntaje de color):
    # en fotos reales el casco, la carrocería o un letrero también pueden ser amarillos o blancos.
    def _calidad(par):
        d, l = par
        formato = max(classifier.por_formato(l["texto"]).values()) if l["texto"] else 0
        return (formato >= 0.6, formato, l["confianza"], d.score)

    mejor = max(zip(dets, lecturas), key=_calidad) if dets else None

    # Se descartan candidatos secundarios sin texto legible (ruedas, faros, letreros)
    pares = [(d, l) for d, l in zip(dets, lecturas) if max(classifier.por_formato(l["texto"]).values()) >= 0.6 or (mejor and d is mejor[0])]
    if pares:
        dets, lecturas = [p[0] for p in pares], [p[1] for p in pares]
        if mejor:
            i = dets.index(mejor[0])
            dets.insert(0, dets.pop(i)); lecturas.insert(0, lecturas.pop(i))

    placa = (placa_manual or (mejor[1]["texto"] if mejor else "")).upper()
    t = time.perf_counter()
    if mejor and not placa_manual:
        if not (mejor[1]["motor"].startswith("Red OCR") and mejor[1]["confianza"] >= 0.9):
            # solo si la lectura es dudosa se decide carro/moto con la imagen (6/G, 0/D, 8/B…)
            placa = _resolver_carro_moto(mejor[1]["texto_bruto"], placa, mejor[0].recorte)
        mejor[1]["texto"] = placa
    clasif = classifier.clasificar(placa, mejor[0].recorte) if mejor else None
    tiempos["clasificación"] = time.perf_counter() - t

    # ¿La lectura es confiable? Si no, NO se emite resultado: se pide confirmación al agente.
    # (Una lectura incompleta reconstruida como placa válida llevaría a consultar otro vehículo.)
    if placa_manual:
        calidad = {"requiere_confirmacion": False, "motivos": [], "correcciones": 0}
    elif mejor:
        calidad = ocr.evaluar_lectura(mejor[1]["texto_bruto"], placa, mejor[1]["confianza"])
    else:
        calidad = {"requiere_confirmacion": False, "motivos": [], "correcciones": 0}

    resultado_alerta, scraping_res = None, {}
    if placa and not calidad["requiere_confirmacion"]:
        t = time.perf_counter()
        resultado_alerta, scraping_res = consultar(placa, clasif, fuentes_scraping, navegador_visible, anonimizar, origen)
        tiempos["consulta"] = time.perf_counter() - t

    sugerencias = []
    if placa and (calidad["requiere_confirmacion"] or (resultado_alerta and not resultado_alerta["registrado"])):
        sugerencias = db.placas_similares(placa)
        if mejor:
            sugerencias += [p for p in db.placas_similares(ocr._limpiar(mejor[1]["texto_bruto"])) if p not in sugerencias]

    anotada = detection.dibujar(base, dets, [l["texto"] or None for l in lecturas])
    tiempos["total"] = time.perf_counter() - t0
    return {
        "etapas": etapas, "detecciones": dets, "lecturas": lecturas, "anotada": anotada,
        "placa": placa, "clasificacion": clasif, "alerta": resultado_alerta,
        "scraping": scraping_res, "tiempos": tiempos,
        "requiere_confirmacion": calidad["requiere_confirmacion"], "motivos_confirmacion": calidad["motivos"],
        "sugerencias": sugerencias,
    }


def _recorte_original(original, base, d, margen=0.04):
    """Recorta la placa en la imagen original, escalando la caja detectada sobre la imagen preprocesada."""
    fy, fx = original.shape[0] / base.shape[0], original.shape[1] / base.shape[1]
    mx, my = d.w * margen, d.h * margen
    y1, y2 = int(max(0, (d.y - my) * fy)), int(min(original.shape[0], (d.y + d.h + my) * fy))
    x1, x2 = int(max(0, (d.x - mx) * fx)), int(min(original.shape[1], (d.x + d.w + mx) * fx))
    rec = original[y1:y2, x1:x2]
    return rec if rec.size else d.recorte


def _resolver_carro_moto(bruto: str, placa: str, recorte):
    """Si la lectura admite una versión de carro (ABC123) y otra de moto (ABC12D) casi igual de
    probables (confusiones 6/G, 0/D, 8/B…), decide con la clasificación visual del recorte."""
    cands = ocr.candidatos_placa(bruto)
    if not cands:
        return placa
    mejor_costo = cands[0][2]
    alternativas = {}
    for texto, tipo, costo in cands:
        if costo <= mejor_costo + 2 and tipo not in alternativas:
            alternativas[tipo] = (texto, costo)
    if len(alternativas) < 2:
        return placa
    puntajes = {}
    for tipo, (texto, costo) in alternativas.items():
        p = classifier.clasificar(texto, recorte)["probabilidades"]
        puntajes[texto] = p[f"nacional_{tipo}"] - 0.05 * costo
    return max(puntajes, key=puntajes.get)


def consultar(placa, clasif=None, fuentes_scraping=None, navegador_visible=True, anonimizar=True, origen="manual"):
    placa = placa.upper().strip()
    local = db.registro_completo(placa)
    scraping_res = {}
    if fuentes_scraping:
        scraping_res = scraper.consultar_todas(placa, fuentes_scraping, visible=navegador_visible)
    datos_scraping = {scraper.FUENTES[f]["nombre"]: r.datos for f, r in scraping_res.items() if r.datos}
    servicio_publico = bool(local["vehiculo"] and "público" in (local["vehiculo"]["servicio"] or "").lower())
    res = alerts.evaluar(placa, clasif, local, datos_scraping, servicio_publico)
    res["local"] = local
    fuentes = ["local"] + [f for f, r in scraping_res.items() if r.datos]
    db.registrar_consulta(placa, (clasif or {}).get("clase", "—"), res["categoria"], res["nivel"],
                          fuentes, origen, anonimizar)
    return res, scraping_res
