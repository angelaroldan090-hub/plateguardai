"""Scraping de portales públicos de tránsito para el cruce de registros.

Fuentes:
  * Movilidad Medellín  (requiere iniciar sesión en el portal: se hace UNA vez, a mano,
                         en la ventana del navegador que abre el scraper; la sesión queda
                         guardada en data/browser_profile)
  * SIMIT (Federación Colombiana de Municipios) — estado de cuenta por placa
  * RUNT — consulta ciudadana (tiene CAPTCHA: el scraper abre la página, el usuario
           resuelve el CAPTCHA y el scraper lee el resultado)

Buenas prácticas implementadas:
  - Resultados vigentes 2 h por placa y fuente; ingesta continua cada 2 h como máximo.
  - Pausa entre consultas y un solo navegador (no se satura el portal).
  - No se evaden CAPTCHAs ni inicios de sesión: los resuelve una persona.
  - Ley 1581 de 2012: solo se extraen datos del vehículo, no del propietario.

Requiere:  pip install playwright beautifulsoup4  &&  playwright install chromium
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass

from bs4 import BeautifulSoup

from . import database as db
from .config import MODO_NUBE, SCRAPER_PROFILE_DIR, SESION_FILE, credenciales_medellin

FUENTES = {
    "medellin": {
        "nombre": "Movilidad Medellín",
        "url": "https://www.medellin.gov.co/portal-movilidad/index.html#/inicio-home",
        "login": "https://www.medellin.gov.co/irj/portal/medellin/servicios_digitales_movilidad",
        "requiere_humano": "Inicio de sesión (una vez)",
    },
    "simit": {
        "nombre": "SIMIT",
        "url": "https://www.fcm.org.co/simit/#/estado-cuenta",
        "login": None,
        "requiere_humano": "Verificación anti-robots ocasional",
    },
    "runt": {
        "nombre": "RUNT",
        "url": "https://portalpublico.runt.gov.co/#/consulta-vehiculo/consulta/consulta-ciudadana",
        "login": None,
        "requiere_humano": "CAPTCHA + documento del propietario",
    },
}

PAUSA_ENTRE_CONSULTAS = 3.0  # segundos
ESPERA_MEDELLIN_SEG = 120    # el portal de Medellín es lento: hasta 2 minutos por paso


# ---------------------------------------------------------------------------
# Parser: convierte el HTML del resultado en registros normalizados.
# Es independiente del navegador para poder probarlo con HTML guardado.
# ---------------------------------------------------------------------------
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


PALABRAS = {
    "multa": ["comparendo", "multa", "infraccion", "sancion", "acuerdo de pago", "deuda", "saldo"],
    "documento": ["soat", "tecnico mecanica", "tecnomecanica", "revision tecnica", "rtm", "poliza"],
    "vencido": ["vencid", "no vigente", "sin vigencia", "expirad"],
    "reporte": ["hurto", "hurtado", "robado", "denuncia", "requerido", "orden de captura",
                "embargo", "delito", "inmovilizado", "evento ilegal", "piques"],
    "sin_novedad": ["no tiene comparendos", "no registra", "no se encontraron", "paz y salvo",
                    "sin multas", "no posee"],
}

RE_VALOR = re.compile(r"\$\s?([\d\.\,]+)")
RE_FECHA = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})")


def _parsear_generico(html: str, fuente: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    filas = []
    for tr in soup.select("table tr"):
        celdas = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if celdas and any(celdas):
            filas.append(" | ".join(celdas))
    texto = soup.get_text("\n", strip=True)
    bloques = filas or [l for l in texto.split("\n") if len(l) > 3]

    multas, documentos, reportes = [], [], []
    for b in bloques:
        n = _norm(b)
        if any(p in n for p in PALABRAS["reporte"]):
            reportes.append({"tipo": _tipo_reporte(n), "descripcion": b[:200], "fuente": FUENTES[fuente]["nombre"]})
        elif any(p in n for p in PALABRAS["documento"]):
            fecha = RE_FECHA.search(b)
            documentos.append({
                "documento": "SOAT" if "soat" in n or "poliza" in n else "Revisión técnico-mecánica",
                "vence": fecha.group(1) if fecha else None,
                "vencido": any(p in n for p in PALABRAS["vencido"]),
                "texto": b[:200],
            })
        elif any(p in n for p in PALABRAS["multa"]) and not any(p in n for p in PALABRAS["sin_novedad"]):
            v = RE_VALOR.search(b)
            multas.append({
                "descripcion": b[:200],
                "valor": float(re.sub(r"[\.\,]", "", v.group(1))) if v else None,
                "estado": "Pagada" if "pagad" in n else "Pendiente",
                "inmoviliza": int("inmoviliz" in n),
            })
    sin_novedad = any(p in _norm(texto) for p in PALABRAS["sin_novedad"]) and not (multas or reportes)
    return {"fuente": fuente, "multas": multas, "documentos": documentos, "reportes": reportes,
            "sin_novedad": sin_novedad, "texto_extraido": texto[:3000]}


def parsear_resultado(html: str, fuente: str) -> dict:
    """Convierte el HTML de la página de resultados en registros normalizados."""
    if fuente == "medellin":
        return parsear_medellin(html)
    if fuente == "simit":
        return parsear_simit(html)
    return _parsear_generico(html, fuente)


def _lineas(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    return [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]


def _valor_tras(lineas: list[str], clave: str) -> str | None:
    """Valor de la línea siguiente a la que contiene `clave` (tablas Concepto | Estado)."""
    for i, l in enumerate(lineas):
        if clave in _norm(l):
            resto = l.split("?")[-1].strip() if "?" in l else ""
            if resto:
                return resto
            return lineas[i + 1] if i + 1 < len(lineas) else None
    return None


def _es_no(v: str | None) -> bool:
    return v is None or _norm(v) in ("no", "no registra", "ninguna", "ninguno", "0", "")


# --- Movilidad Medellín: Trámites y servicios > Consultas > Estado del vehículo -------------
CONCEPTOS_MEDELLIN = {
    "pendientes judiciales": "¿Tiene pendientes judiciales?",
    "prenda a favor": "¿Tiene prenda a favor de la entidad financiera?",
    "multas asociadas": "¿Tiene multas asociadas al vehículo o propietario?",
    "tasas municipales": "Vigencias de tasas de sistematización pendientes",
    "estado actual del vehiculo": "Estado actual del vehículo",
    "se encuentra inmovilizado": "¿Se encuentra inmovilizado?",
}
# Nota: claves comparadas con el texto normalizado (sin tildes, minúsculas) de la columna Concepto.


def _tabla_medellin(html: str) -> dict[str, str] | None:
    """Filas Concepto -> Estado de la tabla de resultados. None si la tabla no está en la página."""
    soup = BeautifulSoup(html, "html.parser")
    for tabla in soup.find_all("table"):
        filas = {}
        encabezado = False
        for tr in tabla.find_all("tr"):
            celdas = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            if not celdas:
                continue
            if _norm(celdas[0]) == "concepto":
                encabezado = True
                continue
            if len(celdas) >= 2:
                filas[celdas[0]] = re.sub(r"\s*Descargar Certificado.*$", "", celdas[1]).strip()
        if encabezado and filas:
            return filas
    return None


def parsear_medellin(html: str) -> dict:
    lineas = _lineas(html)
    texto = _norm(" ".join(lineas))
    base = {"fuente": "medellin", "multas": [], "documentos": [], "reportes": [], "informativo": [],
            "detalle": [], "sin_novedad": False, "texto_extraido": "\n".join(lineas)[:3000]}
    if "no se encuentra matriculado" in texto:
        base["informativo"].append("El vehículo no está matriculado en Medellín (consulte la secretaría de origen).")
        base["no_matriculado"] = True
        return base
    filas = _tabla_medellin(html)
    if not filas:
        # Sin la tabla de resultados NO se interpreta el resto del texto (evita alertas falsas)
        base["error_lectura"] = True
        return base
    v = {}
    for clave in CONCEPTOS_MEDELLIN:
        v[clave] = next((est for con, est in filas.items() if clave in _norm(con)), None)
    base["detalle"] = [{"Concepto": c, "Estado": e} for c, e in filas.items()]
    nombre = "Movilidad Medellín"
    if not _es_no(v["pendientes judiciales"]):
        base["multas"].append({"descripcion": f"Pendientes judiciales: {v['pendientes judiciales']}",
                               "estado": "Pendiente", "inmoviliza": 0, "valor": None})
    if not _es_no(v["multas asociadas"]):
        base["multas"].append({"descripcion": "Multas asociadas al vehículo o propietario",
                               "estado": "Pendiente", "inmoviliza": 0, "valor": None})
    if not _es_no(v["tasas municipales"]):
        base["multas"].append({"descripcion": f"Tasas de sistematización pendientes: {v['tasas municipales']}",
                               "estado": "Pendiente", "inmoviliza": 0, "valor": None})
    if not _es_no(v["se encuentra inmovilizado"]):
        base["reportes"].append({"tipo": "clonacion", "fuente": nombre,
                                 "descripcion": "Figura inmovilizado en patios, pero el vehículo está circulando"})
    estado = v["estado actual del vehiculo"]
    if estado and _norm(estado) != "activo":
        hurto = any(p in _norm(estado) for p in ("hurt", "robad"))
        base["reportes"].append({"tipo": "hurto" if hurto else "clonacion", "fuente": nombre,
                                 "descripcion": f"Estado del vehículo en el registro: {estado}"})
    if not _es_no(v["prenda a favor"]):
        base["informativo"].append("Tiene prenda a favor de una entidad financiera")
    base["sin_novedad"] = not (base["multas"] or base["reportes"])
    return base


# --- SIMIT: Estado de cuenta ------------------------------------------------------------------
RE_RESUMEN = {
    "comparendos": re.compile(r"comparendos:\s*(\d+)"),
    "multas": re.compile(r"multas:\s*(\d+)"),
    "acuerdos": re.compile(r"acuerdos de pago:\s*(\d+)"),
}
RE_TOTAL = re.compile(r"total(?:\s*\(\d+\))?:\s*\$\s*([\d\.\,]+)")


def _pesos(t: str | None) -> float | None:
    if not t:
        return None
    m = re.search(r"\$\s*([\d\.\,]+)", t)
    return float(re.sub(r"[\.\,]", "", m.group(1))) if m else None


def parsear_simit(html: str) -> dict:
    lineas = _lineas(html)
    texto = _norm(" ".join(lineas))
    base = {"fuente": "simit", "multas": [], "documentos": [], "reportes": [], "informativo": [],
            "detalle": [], "resumen": {}, "sin_novedad": False, "texto_extraido": "\n".join(lineas)[:3000]}
    if "no tienes comparendos ni multas" in texto:
        base["sin_novedad"] = True
        base["resumen"] = {"comparendos": 0, "multas": 0, "acuerdos": 0, "total": 0}
        return base
    for k, rx in RE_RESUMEN.items():
        m = rx.search(texto)
        if m:
            base["resumen"][k] = int(m.group(1))
    m = RE_TOTAL.search(texto)
    if m:
        base["resumen"]["total"] = float(re.sub(r"[\.\,]", "", m.group(1)))

    # Tabla "Comparendos y Multas": Tipo | Notificación | Placa | Secretaría | Infracción | Estado | Valor | Valor a pagar
    soup = BeautifulSoup(html, "html.parser")
    for tabla in soup.find_all("table"):
        cab = [_norm(th.get_text(" ", strip=True)) for th in tabla.find_all("th")]
        if not any("infracc" in c for c in cab):
            continue
        for tr in tabla.find_all("tr"):
            celdas = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            celdas = [re.split(r"\s*Detalle Pago", c)[0].strip() for c in celdas]
            if len(celdas) < 6:
                continue
            fila = dict(zip(["tipo", "notificacion", "placa", "secretaria", "infraccion", "estado", "valor", "valor_pagar"],
                            celdas + [""] * 8))
            estado = fila["estado"]
            base["detalle"].append({"Tipo": fila["tipo"], "Placa": fila["placa"], "Secretaría": fila["secretaria"],
                                    "Infracción": fila["infraccion"], "Estado": estado, "Valor a pagar": fila["valor_pagar"]})
            base["multas"].append({
                "descripcion": f"{fila['tipo']} · {fila['infraccion']} · {estado} · {fila['secretaria']}",
                "valor": _pesos(fila["valor_pagar"]) or _pesos(fila["valor"]),
                "estado": "Pagada" if "pagad" in _norm(estado) else "Pendiente",
                "inmoviliza": int("inmoviliz" in _norm(fila["infraccion"])),
            })
    # Si la tabla no se pudo leer pero el resumen indica deudas, se registra igual
    n = base["resumen"].get("comparendos", 0) + base["resumen"].get("multas", 0)
    if n and not base["multas"]:
        base["multas"].append({"descripcion": f"SIMIT reporta {n} comparendo(s)/multa(s) pendientes",
                               "valor": base["resumen"].get("total"), "estado": "Pendiente", "inmoviliza": 0})
    if base["resumen"].get("acuerdos"):
        base["informativo"].append(f"Acuerdos de pago vigentes: {base['resumen']['acuerdos']}")
    if not base["resumen"] and not base["multas"]:
        base["error_lectura"] = True
    base["sin_novedad"] = not base["multas"] and not base.get("error_lectura")
    return base


def _tipo_reporte(n: str) -> str:
    if any(p in n for p in ["hurto", "hurtado", "robado"]):
        return "hurto"
    if any(p in n for p in ["evento ilegal", "piques"]):
        return "evento_ilegal"
    if "clon" in n:
        return "clonacion"
    return "delito"


# ---------------------------------------------------------------------------
# Navegador (Playwright) con perfil persistente
# ---------------------------------------------------------------------------
@dataclass
class ResultadoScraping:
    ok: bool
    datos: dict | None = None
    mensaje: str = ""
    desde_cache: bool = False
    pendiente: bool = False
    fecha: str | None = None


VIGENCIA_HORAS = 2  # coincide con la ingesta continua (cada 2 h como máximo)


def playwright_disponible() -> bool:
    if MODO_NUBE:
        return False
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _contexto(pw, visible=True):
    SCRAPER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        str(SCRAPER_PROFILE_DIR), headless=not visible, locale="es-CO",
        viewport={"width": 1280, "height": 900},
    )
    # Las cookies "de sesión" se pierden al cerrar el navegador: se restauran desde el archivo guardado
    if SESION_FILE.exists():
        try:
            ctx.add_cookies(json.loads(SESION_FILE.read_text())["cookies"])
        except Exception:
            pass
    return ctx


def _guardar_sesion(ctx):
    try:
        SESION_FILE.write_text(json.dumps(ctx.storage_state()))
    except Exception:
        pass


def _en_login_medellin(page) -> bool:
    return "servicios_digitales_movilidad" in page.url or page.locator("input[name='passw']").count() > 0


def _login_medellin_automatico(page) -> bool:
    """Inicia sesión con la cuenta configurada en secrets.toml [medellin]. True si lo logró."""
    cred = credenciales_medellin()
    if not cred:
        return False
    url_login = FUENTES["medellin"]["login"]
    if "servicios_digitales_movilidad" not in page.url:
        page.goto(url_login, wait_until="domcontentloaded", timeout=45000)
    page.locator("input[name='user']").first.fill(cred[0])
    page.locator("input[name='passw']").first.fill(cred[1])
    page.locator("input.divLoginIngresar, input[type='submit'][value*='ngresar'], button:has-text('Ingresar')").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    return page.locator("input[name='passw']:visible").count() == 0


def abrir_para_login(fuente: str = "medellin", espera_seg: int = 180) -> str:
    """Abre el navegador del scraper en el portal para iniciar sesión (a mano, o automática si hay
    credenciales configuradas). La sesión se guarda y se reutiliza en las consultas."""
    from playwright.sync_api import sync_playwright
    url = FUENTES[fuente]["login"] or FUENTES[fuente]["url"]
    with sync_playwright() as pw:
        ctx = _contexto(pw, visible=True)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=ESPERA_MEDELLIN_SEG * 1000)
        page.wait_for_timeout(2000)
        if fuente == "medellin" and _login_medellin_automatico(page):
            _guardar_sesion(ctx)
            ctx.close()
            return "Sesión de Movilidad Medellín iniciada automáticamente y guardada."
        # inicio de sesión manual: se espera hasta que desaparezca el formulario de ingreso
        limite = time.time() + espera_seg
        while time.time() < limite:
            page.wait_for_timeout(2000)
            try:
                if page.locator("input[name='passw']:visible").count() == 0 and "irj/portal" not in page.url:
                    break
            except Exception:
                break
        page.wait_for_timeout(3000)
        _guardar_sesion(ctx)
        ctx.close()
    return f"Sesión de {FUENTES[fuente]['nombre']} guardada."


def verificar_sesion_medellin(visible: bool = False) -> str:
    """Abre la consulta de Medellín para mantener viva la sesión; si venció, intenta el ingreso automático."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _contexto(pw, visible=visible)
        page = ctx.new_page()
        page.goto(FUENTES["medellin"]["url"], wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        if not _en_login_medellin(page):
            _guardar_sesion(ctx)
            ctx.close()
            return "activa"
        ok = _login_medellin_automatico(page)
        if ok:
            _guardar_sesion(ctx)
        ctx.close()
        return "renovada" if ok else "vencida"


def puede_scrapear_aqui() -> bool:
    """True en el computador local (con Playwright); False en la versión web."""
    return playwright_disponible()


def consultar_fuente(placa: str, fuente: str, visible: bool = True, usar_cache: bool = True,
                     espera_resultado_seg: int = 25) -> ResultadoScraping:
    """Devuelve el resultado de una fuente en línea.

    1. Si hay un resultado guardado de menos de 2 h (vigencia de la ingesta), se usa.
    2. En el computador local se ejecuta el scraping y se guarda en la base de datos.
    3. En la versión web se deja una solicitud en cola para el nodo local; mientras tanto se
       devuelve el último resultado guardado (si existe) marcado como pendiente.
    """
    from datetime import datetime, timezone
    placa = placa.upper().strip()
    guardado = db.cache_get(placa, fuente)
    if guardado:
        datos, fecha = guardado
        fresco = (datetime.now(timezone.utc) - fecha).total_seconds() < VIGENCIA_HORAS * 3600
        if usar_cache and fresco:
            return ResultadoScraping(True, datos, f"Resultado de la última ingesta ({db.hora_local(fecha)})",
                                     desde_cache=True, fecha=db.hora_local(fecha))

    if not puede_scrapear_aqui():
        db.crear_solicitud(placa, fuente)
        if guardado:
            return ResultadoScraping(True, guardado[0], f"Resultado anterior ({db.hora_local(guardado[1])}); "
                                     "se solicitó una actualización al nodo local", desde_cache=True,
                                     pendiente=True, fecha=db.hora_local(guardado[1]))
        return ResultadoScraping(False, None, "Consulta enviada al nodo de scraping. Pulse «Actualizar» en unos segundos.",
                                 pendiente=True)
    return ejecutar_scraping(placa, fuente, visible, espera_resultado_seg)


def ejecutar_scraping(placa: str, fuente: str, visible: bool = True, espera_resultado_seg: int = 25) -> ResultadoScraping:
    """Abre el portal con Playwright, lee el resultado y lo guarda en la base de datos."""
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    global _ultima_captura
    _ultima_captura = None
    url = FUENTES[fuente]["url"].format(placa=placa)
    if fuente == "medellin":
        espera_resultado_seg = max(espera_resultado_seg, ESPERA_MEDELLIN_SEG)
    t_carga = max(45, espera_resultado_seg) * 1000
    try:
        with sync_playwright() as pw:
            ctx = _contexto(pw, visible=visible)
            page = ctx.new_page()
            for intento in range(3):   # el portal de Medellín a veces cierra la conexión: se reintenta
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=t_carga)
                    break
                except Exception:
                    if intento == 2:
                        raise
                    page.wait_for_timeout(5000)
            page.wait_for_timeout(3000)

            if fuente == "medellin":
                if _en_login_medellin(page):
                    if not _login_medellin_automatico(page):
                        ctx.close()
                        return ResultadoScraping(False, None, "El portal de Medellín pidió iniciar sesión. Configure la "
                                                 "cuenta en secrets.toml [medellin] o ejecute: python nodo_scraping.py --login")
                    page.goto(url, wait_until="domcontentloaded", timeout=t_carga)
                    page.wait_for_timeout(3000)
                try:
                    html = _buscar_medellin(page, placa, espera_resultado_seg)
                except Exception:
                    _capturar(page, fuente)
                    raise
                _guardar_sesion(ctx)
            elif fuente == "simit":
                html = _buscar_simit(page, placa, espera_resultado_seg)
            else:
                try:
                    page.wait_for_selector("table, .resultado, .alert, [class*='result']",
                                           timeout=espera_resultado_seg * 1000)
                except PWTimeout:
                    pass
                html = page.content()
            ctx.close()
    except Exception as e:
        return ResultadoScraping(False, None, f"Error de scraping: {str(e).splitlines()[0]}"
                                 + (f" · Captura: {_ultima_captura}" if _ultima_captura else ""))

    datos = parsear_resultado(html, fuente)
    time.sleep(PAUSA_ENTRE_CONSULTAS)
    if datos.get("error_lectura"):
        return ResultadoScraping(False, datos, "La página cargó pero no se encontraron resultados legibles "
                                 "(¿verificación anti-robots sin completar o cambió el portal?)")
    db.cache_set(placa, fuente, datos)
    return ResultadoScraping(True, datos, "Consulta en línea completada")


def _esperar_texto(page, textos: list[str], espera_seg: int) -> bool:
    """Espera hasta que aparezca alguno de los textos (la persona puede resolver un CAPTCHA mientras tanto)."""
    limite = time.time() + espera_seg
    while time.time() < limite:
        cuerpo = _norm(page.inner_text("body"))
        if any(_norm(t) in cuerpo for t in textos):
            page.wait_for_timeout(1200)  # termina de pintar la tabla
            return True
        page.wait_for_timeout(700)
    return False


_ultima_captura = None


def _capturar(page, fuente: str):
    """Guarda una captura de la página cuando algo falla (data/scraper_debug/)."""
    global _ultima_captura
    try:
        from .config import DATA_DIR
        d = DATA_DIR / "scraper_debug"
        d.mkdir(parents=True, exist_ok=True)
        ruta = d / f"{fuente}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(ruta), full_page=True)
        _ultima_captura = str(ruta)
    except Exception:
        _ultima_captura = None


def _clic_visible(page, texto: str, timeout: int = 15000, hover: bool = False):
    """Hace clic (o pasa el mouse) sobre el primer elemento VISIBLE cuyo propio texto es `texto`
    (sirve para menús donde el elemento también contiene un submenú oculto)."""
    loc = page.locator(f"xpath=//*[text()[normalize-space()='{texto}']]").locator("visible=true")
    if not loc.count():
        loc = page.get_by_text(texto, exact=True).locator("visible=true")
    loc = loc.first
    loc.wait_for(state="visible", timeout=timeout)
    if hover:
        loc.hover()
    else:
        loc.click()
    page.wait_for_timeout(900)


def _visible_texto(page, texto: str):
    return page.locator(f"xpath=//*[text()[normalize-space()='{texto}']]").locator("visible=true")


def _esperar_visible(page, texto: str, seg: float) -> bool:
    limite = time.time() + seg
    while time.time() < limite:
        if _visible_texto(page, texto).count():
            return True
        page.wait_for_timeout(300)
    return False


def _ir_a_estado_vehiculo(page):
    """Trámites y servicios -> Consultas -> Estado del vehículo, como lo hace una persona.
    Si el submenú no se despliega, activa directamente la opción (existe en la página aunque esté oculta)."""
    _clic_visible(page, "Trámites y servicios", timeout=ESPERA_MEDELLIN_SEG * 1000)
    _esperar_visible(page, "Consultas", 5)
    cons = _visible_texto(page, "Consultas").first
    # 1) pasar el mouse sobre "Consultas" (el submenú se abre hacia la derecha)
    try:
        caja = cons.bounding_box()
        if caja:
            page.mouse.move(caja["x"] + 10, caja["y"] + caja["height"] / 2)
            page.mouse.move(caja["x"] + caja["width"] - 5, caja["y"] + caja["height"] / 2, steps=8)
    except Exception:
        pass
    if not _esperar_visible(page, "Estado del vehículo", 3):
        # 2) clic sobre "Consultas"
        try:
            cons.click()
        except Exception:
            pass
        _esperar_visible(page, "Estado del vehículo", 3)
    if _visible_texto(page, "Estado del vehículo").count():
        _visible_texto(page, "Estado del vehículo").first.click()
    else:
        # 3) activar la opción aunque esté oculta (dispara la misma navegación del portal)
        ok = page.evaluate("""() => {
            const el = [...document.querySelectorAll('a, li, span, button')]
              .find(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim() === 'Estado del vehículo'));
            if (!el) return false;
            (el.closest('a') || el).click();
            return true;
        }""")
        if not ok:
            raise RuntimeError("No se encontró la opción 'Estado del vehículo' en el menú")
    page.wait_for_timeout(1500)


def _boton_buscar(page):
    return page.locator("xpath=//*[(self::button or self::a or self::input) and "
                        "(normalize-space(.)='Buscar' or @value='Buscar')]").locator("visible=true").first


def _casilla_placa_medellin(page):
    """Casilla de la placa en Estado del vehículo (placeholder 'Ingrese una placa', nov. 2026)."""
    for loc in (page.get_by_placeholder("Ingrese una placa"),
                page.locator("input[placeholder*='placa' i]"),
                page.locator("xpath=//*[normalize-space(text())='Placa']/following::input[not(@type='hidden')][1]"),
                page.locator("xpath=//*[(self::button or self::a or self::input) and (normalize-space(.)='Buscar' or @value='Buscar')]"
                             "/preceding::input[not(@type='hidden')][1]")):
        loc = loc.locator("visible=true")
        if loc.count():
            return loc.first
    return None


def _buscar_medellin(page, placa: str, espera_seg: int) -> str:
    # Ruta de una persona: Trámites y servicios -> Consultas -> Estado del vehículo -> placa -> Buscar
    if _casilla_placa_medellin(page) is None:
        _ir_a_estado_vehiculo(page)
    campo = None
    limite = time.time() + ESPERA_MEDELLIN_SEG
    while time.time() < limite and campo is None:
        campo = _casilla_placa_medellin(page)
        if campo is None:
            page.wait_for_timeout(500)
    if campo is None:
        raise RuntimeError("No se encontró la casilla 'Ingrese una placa' en Estado del vehículo")
    campo.click()
    campo.fill("")
    campo.press_sequentially(placa, delay=90)
    page.wait_for_timeout(400)
    if not _clic_buscar(page, campo, espera_seg):
        _guardar_html_debug(page, campo, "medellin")
        raise RuntimeError("Se escribió la placa pero no aparecieron resultados tras pulsar Buscar")
    page.wait_for_timeout(1200)
    return page.content()


def _resultado_medellin_visible(page) -> bool:
    try:
        if page.locator("table").filter(has_text="Concepto").locator("visible=true").count():
            return True
        return "no se encuentra matriculado" in _norm(page.inner_text("body"))
    except Exception:
        return False


def _esperar_resultado_medellin(page, seg: float) -> bool:
    limite = time.time() + seg
    while time.time() < limite:
        if _resultado_medellin_visible(page):
            return True
        page.wait_for_timeout(500)
    return False


def _clic_buscar(page, campo, espera_seg: int) -> bool:
    """Pulsa 'Buscar' como una persona y verifica que aparezcan los resultados.
    Prueba varias formas hasta que la tabla aparezca. Devuelve True si hubo resultados."""
    caja_campo = campo.bounding_box() or {"x": 0, "y": 0, "width": 0, "height": 0}

    def _mas_cercano(loc):
        mejor, dist = None, 1e9
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                c = el.bounding_box()
                d = abs(c["y"] - caja_campo["y"]) + abs(c["x"] - (caja_campo["x"] + caja_campo["width"]))
                if d < dist:
                    mejor, dist = el, d
            except Exception:
                continue
        return mejor

    def clic_mouse_texto():
        el = _mas_cercano(page.get_by_text("Buscar", exact=True))
        if el is None:
            return False
        c = el.bounding_box()
        page.mouse.click(c["x"] + c["width"] / 2, c["y"] + c["height"] / 2)
        return True

    def clic_boton_siguiente():
        el = campo.locator("xpath=following::*[self::button or self::a or self::input[@type='button' or @type='submit']][1]")
        if not el.count():
            return False
        el.first.scroll_into_view_if_needed()
        el.first.click(force=True, timeout=5000)
        return True

    def enter():
        campo.click()
        campo.press("Enter")
        return True

    def clic_js():
        return page.evaluate("""() => {
            const el = [...document.querySelectorAll('button, a, input, span, div')]
              .filter(e => e.offsetParent !== null)
              .find(e => ((e.innerText || e.value || '').trim().toLowerCase() === 'buscar'));
            if (!el) return false;
            ['mousedown', 'mouseup', 'click'].forEach(t => el.dispatchEvent(new MouseEvent(t, {bubbles: true})));
            return true;
        }""")

    for intento in (clic_mouse_texto, clic_boton_siguiente, enter, clic_js):
        try:
            if intento() and _esperar_resultado_medellin(page, 10):
                return True
        except Exception:
            continue
    return _esperar_resultado_medellin(page, espera_seg)


def _guardar_html_debug(page, campo, fuente: str):
    """Guarda el HTML alrededor de la casilla para ajustar el scraper si el portal cambia."""
    try:
        from .config import DATA_DIR
        d = DATA_DIR / "scraper_debug"
        d.mkdir(parents=True, exist_ok=True)
        html = campo.evaluate("e => { let p = e; for (let i = 0; i < 5 && p.parentElement; i++) p = p.parentElement; return p.outerHTML; }")
        (d / f"{fuente}_{time.strftime('%Y%m%d_%H%M%S')}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


def _buscar_simit(page, placa: str, espera_seg: int) -> str:
    # Campo #txtBusqueda y botón de la lupa #btnNumDocPlaca (estructura del portal, nov. 2026)
    campo = page.locator("#txtBusqueda")
    try:
        campo.wait_for(state="visible", timeout=20000)
    except Exception:
        campo = page.get_by_placeholder("Número de identificación o placa del vehículo")
    campo.first.click()
    campo.first.fill("")
    campo.first.press_sequentially(placa, delay=90)   # tecla por tecla, como una persona
    page.wait_for_timeout(500)
    boton = page.locator("#btnNumDocPlaca")
    if boton.count():
        boton.first.click()
    else:
        page.locator("button[aria-label='Realizar consulta'], button[type='submit']").first.click()
    page.wait_for_timeout(1500)
    if not _esperar_texto(page, ["Comparendos y Multas", "No tienes comparendos", "Resumen"], 8):
        campo.first.press("Enter")   # segundo intento
    _esperar_texto(page, ["Comparendos y Multas", "No tienes comparendos", "Resumen"], max(espera_seg, 60))
    return page.content()


def consultar_todas(placa: str, fuentes: list[str], visible: bool = True,
                    esperar_seg: int = 300) -> dict[str, ResultadoScraping]:
    """Consulta todas las fuentes. En la web, si quedaron solicitudes en cola para el nodo, espera
    automáticamente (hasta `esperar_seg`) a que el nodo las resuelva, sin intervención del usuario."""
    res = {f: consultar_fuente(placa, f, visible=visible) for f in fuentes}
    pendientes = [f for f, r in res.items() if r.pendiente]
    if pendientes and esperar_seg and not puede_scrapear_aqui() and db.estado_nodos() and \
            any(n["en_linea"] for n in db.estado_nodos()):
        limite = time.time() + esperar_seg
        while pendientes and time.time() < limite:
            time.sleep(3)
            for f in list(pendientes):
                est = db.estado_solicitud(placa.upper().strip(), f)
                if est and est["estado"] in ("completada", "error"):
                    r = consultar_fuente(placa, f, visible=visible)
                    if est["estado"] == "error" and not r.datos:
                        r = ResultadoScraping(False, None, f"El nodo no pudo consultar: {est.get('mensaje') or ''}")
                    res[f] = r
                    pendientes.remove(f)
    return res
