"""Cruce de registros (base local + scraping) y motor de alertas."""
from __future__ import annotations

from datetime import date, datetime

from .config import CATEGORIAS_ALERTA, PICO_Y_PLACA, ZONA


def pico_y_placa(placa: str, tipo: str, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(ZONA)
    digitos = [c for c in placa if c.isdigit()]
    if not digitos:
        return {"aplica": False, "motivo": "Placa sin dígitos"}
    digito = int(digitos[0] if tipo == "moto" else digitos[-1])
    restringidos = PICO_Y_PLACA["dias"].get(ahora.weekday(), [])
    en_horario = PICO_Y_PLACA["hora_inicio"] <= ahora.hour < PICO_Y_PLACA["hora_fin"]
    aplica = digito in restringidos and en_horario
    return {"aplica": aplica, "digito": digito, "restringidos_hoy": restringidos, "en_horario": en_horario}


def evaluar(placa: str, deteccion: dict | None, local: dict, scraping: dict | None = None,
            servicio_publico: bool = False) -> dict:
    """Devuelve la categoría principal (la de mayor nivel) y todas las alertas encontradas.

    deteccion: salida del clasificador (tipo/naturaleza observados en la imagen), o None si es consulta manual.
    local:     registro de la base local (database.registro_completo).
    scraping:  {fuente: datos_parseados} obtenidos de los portales.
    """
    hallazgos = []  # (categoria, detalle, fuente)
    hoy = datetime.now(ZONA).date()

    # ---- Base local ----
    for m in local.get("multas", []):
        if m["estado"] != "Pagada":
            extra = " (exige inmovilización)" if m.get("inmoviliza") else ""
            hallazgos.append(("MULTAS_DEUDA", f"{m['codigo']} – {m['descripcion']} – ${m['valor']:,.0f}{extra}", "Base local"))
    for d in local.get("documentos", []):
        if d["vence"] and date.fromisoformat(d["vence"]) < hoy:
            hallazgos.append(("DOCUMENTOS_VENCIDOS", f"{d['documento']} vencido desde {d['vence']}", "Base local"))
    for r in local.get("reportes", []):
        cat = "CLONACION" if r["tipo"] == "clonacion" else "ACTO_ILEGAL"
        hallazgos.append((cat, f"{r['tipo'].replace('_', ' ').capitalize()}: {r['descripcion']}", r.get("fuente", "Base local")))

    # ---- Scraping ----
    for fuente, datos in (scraping or {}).items():
        if not datos:
            continue
        for m in datos.get("multas", []):
            if isinstance(m, dict) and m.get("estado") != "Pagada":
                hallazgos.append(("MULTAS_DEUDA", m["descripcion"], fuente))
        for d in datos.get("documentos", []):
            if isinstance(d, dict) and d.get("vencido"):
                hallazgos.append(("DOCUMENTOS_VENCIDOS", d["texto"], fuente))
        for r in datos.get("reportes", []):
            if not isinstance(r, dict):
                continue
            cat = "CLONACION" if r.get("tipo") == "clonacion" else "ACTO_ILEGAL"
            hallazgos.append((cat, r.get("descripcion", ""), fuente))

    # ---- Clonación por inconsistencia (lo observado vs. lo registrado) ----
    # Solo se alerta si el modelo está muy seguro Y el formato del texto también contradice el
    # registro; así un error del modelo no genera una alerta grave contra un ciudadano.
    veh = local.get("vehiculo")
    if veh and deteccion:
        probs = deteccion.get("probabilidades", {})
        from .classifier import por_formato
        fmt = por_formato(placa)
        clase_obs = f"{deteccion.get('naturaleza')}_{deteccion.get('tipo')}"
        seguro = probs.get(clase_obs, 0) >= 0.8
        fmt_registrado = fmt.get(f"{veh['naturaleza']}_{veh['tipo']}", 0) >= 0.6
        if seguro and not fmt_registrado:
            if deteccion.get("tipo") and veh["tipo"] != deteccion["tipo"]:
                hallazgos.append(("CLONACION", f"La placa está registrada como {veh['tipo']} pero se observó un(a) {deteccion['tipo']}", "Cruce imagen/registro"))
            if deteccion.get("naturaleza") and veh["naturaleza"] != deteccion["naturaleza"]:
                hallazgos.append(("CLONACION", f"Naturaleza registrada {veh['naturaleza']} ≠ observada {deteccion['naturaleza']}", "Cruce imagen/registro"))

    # ---- Fuentes que sí verificaron el vehículo ----
    # Una fuente verifica si devolvió una lectura válida del vehículo. "No matriculado en Medellín"
    # o un error de lectura NO verifican nada.
    verificado_en = ["Base de datos del sistema"] if veh else []
    for fuente, datos in (scraping or {}).items():
        if datos and not datos.get("error_lectura") and not datos.get("no_matriculado"):
            verificado_en.append(fuente)

    # ---- Resultado ----
    if hallazgos:
        principal = max(hallazgos, key=lambda h: CATEGORIAS_ALERTA[h[0]]["nivel"])[0]
    elif verificado_en:
        principal = "NORMAL"
    else:
        principal = "SIN_REGISTRO"   # sin información ≠ sin alertas
    info = CATEGORIAS_ALERTA[principal]

    tipo = (deteccion or {}).get("tipo") or (veh or {}).get("tipo") or "carro"
    pyp = pico_y_placa(placa, tipo) if not servicio_publico else {"aplica": False}

    return {
        "placa": placa,
        "categoria": principal,
        "nivel": info["nivel"],
        "info": info,
        "hallazgos": [{"categoria": c, "detalle": d, "fuente": f} for c, d, f in hallazgos],
        "categorias_presentes": sorted({h[0] for h in hallazgos}, key=lambda c: -CATEGORIAS_ALERTA[c]["nivel"]),
        "pico_y_placa": pyp,
        "registrado": veh is not None,
        "verificado_en": verificado_en,
        "vehiculo": veh,
    }
