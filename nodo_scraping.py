"""Nodo de scraping de PlateGuardAI (se ejecuta en el computador local).

Hace dos trabajos en paralelo y de forma continua:
  1. INGESTA CONTINUA: cada `--cada` minutos (por defecto y como máximo 120 = 2 horas) vuelve a
     consultar en SIMIT / Movilidad Medellín todas las placas de la lista de seguimiento y guarda
     los resultados en la base de datos (en la nube), de modo que la información nunca tenga más
     de 2 horas.
  2. SOLICITUDES: atiende al momento las consultas que se piden desde la app web (celular).

Uso:
    python nodo_scraping.py                       # nodo continuo (deje la ventana abierta)
    python nodo_scraping.py --cada 60             # ingesta cada hora
    python nodo_scraping.py --login               # iniciar sesión en el portal de Medellín (una vez)
    python nodo_scraping.py --seguir EGX799,ABC123   # agregar placas a la lista de seguimiento
    python nodo_scraping.py --placas EGX799 --fuentes simit,medellin   # consulta única, imprime lo leído
"""
import argparse
import platform
import random
import sys
import time
from datetime import datetime, timedelta

from core import database as db
from core import scraper

INTERVALO = 5            # segundos entre revisiones de la cola de solicitudes
MAX_MINUTOS_INGESTA = 120  # requisito: ingesta al menos cada 2 horas
NOMBRE = f"nodo-{platform.node()}"


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)


def mostrar_lectura(d):
    """Imprime lo que el lector extrajo de la página (para verificar la primera prueba real)."""
    if not d:
        return
    if d.get("resumen"):
        print("    Resumen:", d["resumen"])
    for fila in d.get("detalle", []):
        print("    ", " | ".join(str(v) for v in fila.values()))
    for m in d.get("multas", []):
        print("     Multa/deuda:", m.get("descripcion"), "-", m.get("valor"))
    for r in d.get("reportes", []):
        print("     Reporte:", r.get("descripcion"))
    for n in d.get("informativo", []):
        print("     Info:", n)
    if d.get("sin_novedad"):
        print("     Sin novedades")
    if d.get("error_lectura"):
        print("     No se pudo leer. Texto de la página:\n", d.get("texto_extraido", "")[:800])


def latido(fuentes, proxima):
    db.latido_nodo(NOMBRE, f"fuentes={','.join(fuentes)}; próxima ingesta {proxima:%H:%M}")


def atender_solicitudes(fuentes, visible) -> int:
    n = 0
    for s in db.tomar_solicitudes():
        if s["fuente"] not in fuentes:
            db.cerrar_solicitud(s["id"], False, "Fuente no habilitada en este nodo")
            continue
        log(f"Solicitud #{s['id']}: {s['placa']} en {scraper.FUENTES[s['fuente']]['nombre']}")
        db.latido_nodo(NOMBRE, f"consultando {s['placa']}")   # la web sabe que el nodo sigue activo
        r = scraper.ejecutar_scraping(s["placa"], s["fuente"], visible=visible)
        db.cerrar_solicitud(s["id"], r.ok, r.mensaje)
        log(f"  -> {'OK' if r.ok else 'ERROR'}: {r.mensaje}")
        n += 1
    return n


def ciclo_ingesta(fuentes, visible, horas_vigencia, proxima) -> tuple[int, int]:
    """Refresca las placas en seguimiento cuyo resultado tiene más de `horas_vigencia`."""
    trabajo = [(p, f) for p, f in db.pendientes_de_ingesta(horas_vigencia) if f in fuentes]
    trabajo.sort(key=lambda pf: 0 if pf[1] == "simit" else 1)   # SIMIT primero, Medellín después
    if not trabajo:
        log("Ingesta: todas las placas en seguimiento están al día.")
        return 0, 0
    id_ = db.iniciar_ingesta(NOMBRE, len({p for p, _ in trabajo}))
    log(f"Ingesta #{id_}: {len(trabajo)} consultas ({len({p for p, _ in trabajo})} placas)")
    ok = err = 0
    try:
        for placa, fuente in trabajo:
            atender_solicitudes(fuentes, visible)   # las consultas de la web tienen prioridad
            r = scraper.ejecutar_scraping(placa, fuente, visible=visible)
            ok, err = ok + r.ok, err + (not r.ok)
            log(f"  {placa} / {scraper.FUENTES[fuente]['nombre']}: {'OK' if r.ok else 'ERROR ' + r.mensaje}")
            latido(fuentes, proxima)
            time.sleep(random.uniform(2, 5))       # pausa para no saturar los portales
        db.cerrar_ingesta(id_, ok, err)
    except Exception as e:
        db.cerrar_ingesta(id_, ok, err, estado=f"interrumpida: {e}"[:60])
        raise
    log(f"Ingesta #{id_} terminada: {ok} OK, {err} con error.")
    return ok, err


def nodo_continuo(fuentes, visible, cada_min):
    log(f"Nodo '{NOMBRE}' conectado a: {db.descripcion_motor()}")
    if not db.es_nube():
        log("ADVERTENCIA: no hay base de datos en la nube configurada; la app web no verá estos resultados.")
    seg = db.lista_seguimiento()
    log(f"Ingesta continua cada {cada_min} min · {len(seg)} placas en seguimiento · fuentes: {', '.join(fuentes)}")
    if not seg:
        log("La lista de seguimiento está vacía. Agregue placas con --seguir o desde la app (Base de datos y scraping).")
    n = db.recuperar_solicitudes()
    if n:
        log(f"Se recuperaron {n} solicitudes que quedaron sin terminar")
    log("Atendiendo solicitudes… (Ctrl+C para salir)")
    proxima = datetime.now()   # primera ingesta al arrancar
    revisar_sesion = datetime.now()
    while True:
        latido(fuentes, proxima)
        atender_solicitudes(fuentes, visible)
        if "medellin" in fuentes and datetime.now() >= revisar_sesion:
            try:
                estado = scraper.verificar_sesion_medellin(visible=False)
                log(f"Sesión de Movilidad Medellín: {estado}")
                if estado == "vencida":
                    log("  Configure [medellin] usuario/clave en .streamlit/secrets.toml o ejecute --login")
            except Exception as e:
                log(f"No se pudo verificar la sesión de Medellín: {e}")
            revisar_sesion = datetime.now() + timedelta(minutes=20)
        if datetime.now() >= proxima:
            try:
                ciclo_ingesta(fuentes, visible, horas_vigencia=cada_min / 60, proxima=proxima)
            except Exception as e:  # un fallo de red no detiene el nodo
                log(f"Error en la ingesta: {e}")
            proxima = datetime.now() + timedelta(minutes=cada_min)
            log(f"Próxima ingesta: {proxima:%Y-%m-%d %H:%M}")
        time.sleep(INTERVALO)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true", help="abrir el portal de Medellín para iniciar sesión")
    ap.add_argument("--placas", help="consulta única de estas placas (separadas por coma)")
    ap.add_argument("--seguir", help="agregar placas a la lista de seguimiento (separadas por coma)")
    ap.add_argument("--fuentes", default="simit,medellin", help="fuentes habilitadas (simit,medellin,runt)")
    ap.add_argument("--cada", type=int, default=MAX_MINUTOS_INGESTA, help="minutos entre ingestas (máx. 120)")
    ap.add_argument("--oculto", action="store_true", help="no mostrar la ventana del navegador")
    args = ap.parse_args()

    db.inicializar()
    fuentes = [f.strip() for f in args.fuentes.split(",") if f.strip() in scraper.FUENTES]

    if args.seguir:
        for p in [x.strip().upper() for x in args.seguir.split(",") if x.strip()]:
            db.agregar_seguimiento(p, ",".join(fuentes), motivo="agregada desde el nodo")
            log(f"{p} agregada a la lista de seguimiento")
        return

    if not scraper.puede_scrapear_aqui():
        sys.exit("Playwright no está disponible. Ejecute: pip install playwright && playwright install chromium")

    if args.login:
        log("Inicie sesión en la ventana del navegador (tiene 3 minutos)…")
        log(scraper.abrir_para_login("medellin", 180))
        return

    if args.placas:
        for placa in [p.strip().upper() for p in args.placas.split(",") if p.strip()]:
            for f in fuentes:
                r = scraper.ejecutar_scraping(placa, f, visible=not args.oculto)
                log(f"{placa} / {scraper.FUENTES[f]['nombre']}: {'OK' if r.ok else 'ERROR'} {r.mensaje}")
                mostrar_lectura(r.datos)
        return

    cada = args.cada
    if cada > MAX_MINUTOS_INGESTA:
        log(f"--cada {cada} supera el máximo permitido; se usa {MAX_MINUTOS_INGESTA} min (2 horas).")
        cada = MAX_MINUTOS_INGESTA
    cada = max(cada, 15)  # mínimo razonable para no saturar los portales
    try:
        nodo_continuo(fuentes, visible=not args.oculto, cada_min=cada)
    except KeyboardInterrupt:
        log("Nodo detenido.")


if __name__ == "__main__":
    main()
