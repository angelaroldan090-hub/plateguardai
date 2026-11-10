"""Componentes visuales reutilizables de la interfaz."""
import base64
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

from core.config import CATEGORIAS_ALERTA

CSS = """
<style>
:root { --azul:#0B1F4B; --azul2:#0A66FF; --gris:#5F6B7A; --linea:#D6DCE4; --fondo:#F4F6F9; --oro:#0A66FF; }
html, body, [class*="css"] { font-family: "Source Sans Pro", "Segoe UI", Arial, sans-serif; }
.block-container { padding-top: 1.2rem; max-width: 1400px; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: var(--azul); }
[data-testid="stSidebar"] * { color: #E6ECF3 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.15); }
[data-testid="stSidebar"] [data-baseweb="select"] > div, [data-testid="stSidebar"] details { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.2); }
[data-testid="stSidebar"] [data-baseweb="select"] span { color: #0B1F4B !important; }
.marca { display:flex; align-items:center; gap:.75rem; padding:.2rem 0 .6rem; border-bottom:2px solid var(--oro); margin-bottom:.8rem; }
.marca img { width:64px; height:auto; }
.marca .nombre { font-weight:800; font-size:1.25rem; letter-spacing:.02em; }
.marca .nombre span { color:#4D94FF !important; }
.marca .sub { font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; opacity:.8; }
.seccion-lbl { font-size:.7rem; text-transform:uppercase; letter-spacing:.12em; opacity:.7; margin:.4rem 0 .2rem; }
.barra { background: var(--azul); color:#fff; padding:.9rem 1.3rem; border-radius:2px; border-bottom:3px solid var(--oro);
  display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:.4rem; }
.barra .ruta { font-size:.72rem; text-transform:uppercase; letter-spacing:.12em; opacity:.75; }
.barra .titulo { font-size:1.55rem; font-weight:700; margin-top:.1rem; }
.barra .logo { height:44px; margin-right:1rem; }
.barra .izq { display:flex; align-items:center; }
.barra .meta { font-size:.75rem; text-align:right; opacity:.85; line-height:1.4; }
.placa { display:inline-block; font-family: "DejaVu Sans Mono", Consolas, monospace; font-weight:800;
  font-size:2.1rem; letter-spacing:.16em; padding:.2rem .9rem; border:3px solid #111; border-radius:4px;
  background:#F2C511; color:#111; }
.placa.blanco { background:#F4F4F4; }
.placa.intl { background:#E8EEF7; }
.alerta { border:1px solid var(--linea); border-left:8px solid; background:#fff; border-radius:2px; margin-bottom:.8rem; }
.alerta .cab { color:#fff; padding:.45rem 1rem; font-size:.75rem; font-weight:700; text-transform:uppercase; letter-spacing:.12em;
  display:flex; justify-content:space-between; }
.alerta .cuerpo { padding:.8rem 1rem 1rem; color:#1A202C; }
.alerta .titulo { font-size:1.35rem; font-weight:700; margin-bottom:.25rem; }
.alerta .protocolo { margin-top:.7rem; padding:.6rem .8rem; background:var(--fondo); border:1px solid var(--linea);
  font-size:.92rem; }
.alerta .protocolo b { text-transform:uppercase; font-size:.72rem; letter-spacing:.1em; color:var(--gris); display:block; }
.chip { display:inline-block; padding:.15rem .55rem; margin:.15rem .3rem .15rem 0; border-radius:2px;
  font-size:.78rem; border:1px solid var(--linea); border-left:4px solid; background:#fff; }
.tarjeta { border:1px solid var(--linea); border-top:3px solid var(--azul2); border-radius:2px; padding:.7rem .9rem; background:#fff; height:100%; }
.tarjeta .k { font-size:.7rem; color:var(--gris); text-transform:uppercase; letter-spacing:.1em; }
.tarjeta .v { font-size:1.1rem; font-weight:700; color:#0B1F4B; }
.paso { font-size:.75rem; color:var(--gris); text-align:center; margin-top:-.4rem; text-transform:uppercase; letter-spacing:.06em; }
.pie { margin-top:2rem; padding-top:.6rem; border-top:1px solid var(--linea); font-size:.72rem; color:var(--gris); }
.stButton button, .stDownloadButton button { border-radius:2px; }
[data-testid="stExpander"] details { border-radius:2px; }

/* Inicio de sesión */
.login-cab { background:var(--azul); border-bottom:3px solid var(--azul2); padding:1.6rem 1rem 1.2rem; text-align:center;
  color:#fff; margin:2rem 0 1rem; }
.login-cab img { width:150px; }
.login-cab .nombre { font-size:1.7rem; font-weight:800; margin-top:.5rem; }
.login-cab .nombre span { color:#4D94FF; }
.login-cab .sub { font-size:.72rem; text-transform:uppercase; letter-spacing:.12em; opacity:.8; }

/* Celular */
@media (max-width: 640px) {
  .block-container { padding: 3.2rem .8rem 1rem; }
  .barra { flex-direction:column; align-items:flex-start; gap:.4rem; padding:.7rem .9rem; }
  .barra .logo { height:34px; margin-right:.7rem; }
  .barra .titulo { font-size:1.2rem; }
  .barra .ruta { display:none; }
  .barra .meta { text-align:left; font-size:.7rem; }
  .placa { font-size:1.6rem; letter-spacing:.1em; }
  .alerta .titulo { font-size:1.15rem; }
  .alerta .cab { flex-direction:column; gap:.1rem; font-size:.68rem; }
  .tarjeta { margin-bottom:.5rem; }
  [data-testid="stSegmentedControl"] button { padding:.3rem .5rem; font-size:.85rem; }
}
</style>
"""


ASSETS = Path(__file__).resolve().parent.parent / "assets"


def logo_b64(nombre: str = "logo_blanco.png") -> str:
    return base64.b64encode((ASSETS / nombre).read_bytes()).decode()


def logo_html() -> str:
    return (f'<div class="marca"><img src="data:image/png;base64,{logo_b64()}" alt="PlateGuardAI">'
            '<div><div class="nombre">PlateGuard<span>AI</span></div>'
            '<div class="sub">Verificación vehicular inteligente</div></div></div>')


def estilos():
    st.markdown(CSS, unsafe_allow_html=True)


def encabezado(titulo: str, modulo: str = "Plataforma de verificación"):
    from datetime import datetime

    from core.config import ZONA
    ahora = datetime.now(ZONA)
    st.markdown(f"""
    <div class="barra">
      <div class="izq"><img class="logo" src="data:image/png;base64,{logo_b64()}">
        <div><div class="ruta">PlateGuardAI / {modulo} / {titulo}</div><div class="titulo">{titulo}</div></div></div>
      <div class="meta">Fecha de consulta: {ahora:%d/%m/%Y}<br>Hora: {ahora:%H:%M}</div>
    </div>""", unsafe_allow_html=True)


def pie():
    st.markdown('<div class="pie">PlateGuardAI · Verificación vehicular inteligente · Proyecto académico. '
                'Tratamiento de datos conforme a la Ley 1581 de 2012. Los registros de la base local son de prueba.</div>',
                unsafe_allow_html=True)


def bgr2rgb(img):
    if img is None:
        return None
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def leer_subida(archivo) -> np.ndarray | None:
    if archivo is None:
        return None
    datos = np.frombuffer(archivo.getvalue(), np.uint8)
    return cv2.imdecode(datos, cv2.IMREAD_COLOR)


def placa_html(texto: str, color: str = "amarillo", naturaleza: str = "nacional") -> str:
    clase = "intl" if naturaleza == "internacional" else ("blanco" if color == "blanco" else "")
    return f'<div class="placa {clase}">{texto or "------"}</div>'


def tarjeta_alerta(res: dict):
    info = res["info"]
    nivel_txt = {0: "Sin riesgo", 1: "Riesgo bajo", 2: "Riesgo medio", 3: "Riesgo alto"}[info["nivel"]]
    st.markdown(f"""
    <div class="alerta" style="border-left-color:{info['color']}">
      <div class="cab" style="background:{info['color']}"><span>Código {info['codigo']}</span><span>Nivel {info['nivel']} · {nivel_txt}</span></div>
      <div class="cuerpo">
        <div class="titulo" style="color:{info['color']}">{info['titulo']}</div>
        <div>{info['descripcion']}</div>
        <div class="protocolo"><b>Protocolo de actuación</b>{info['protocolo']}</div>
      </div>
    </div>""", unsafe_allow_html=True)
    otras = [c for c in res["categorias_presentes"] if c != res["categoria"]]
    if otras:
        st.markdown("Novedades adicionales: " + "".join(
            f'<span class="chip" style="border-left-color:{CATEGORIAS_ALERTA[c]["color"]}">{CATEGORIAS_ALERTA[c]["codigo"]} · {CATEGORIAS_ALERTA[c]["titulo"]}</span>'
            for c in otras), unsafe_allow_html=True)
    pyp = res.get("pico_y_placa", {})
    if pyp.get("aplica"):
        st.warning(f"Restricción vehicular (pico y placa): el dígito {pyp['digito']} tiene restricción en este horario.")
    elif "restringidos_hoy" in pyp:
        hoy = ", ".join(map(str, pyp["restringidos_hoy"])) or "ninguno"
        st.caption(f"Restricción vehicular (pico y placa): sin restricción para el dígito {pyp['digito']}. Dígitos restringidos hoy: {hoy}.")


def tarjeta(k, v):
    st.markdown(f'<div class="tarjeta"><div class="k">{k}</div><div class="v">{v}</div></div>', unsafe_allow_html=True)


def hallazgos_tabla(res: dict):
    import pandas as pd
    if not res["hallazgos"]:
        st.success("No se encontraron registros negativos en las fuentes consultadas.")
        return
    df = pd.DataFrame(res["hallazgos"])
    df["categoría"] = df["categoria"].map(lambda c: f"{CATEGORIAS_ALERTA[c]['codigo']} · {CATEGORIAS_ALERTA[c]['titulo']}")
    st.dataframe(df[["categoría", "detalle", "fuente"]], hide_index=True, use_container_width=True)


def ficha_vehiculo(veh: dict | None):
    if not veh:
        st.info("La placa no está en la base local. Use las fuentes en línea (scraping) para completar la consulta.")
        return
    c = st.columns(2)
    with c[0]:
        tarjeta("Vehículo registrado", f"{veh['marca']} {veh['linea']} · {veh['modelo']}")
        st.write("")
        tarjeta("Tipo registrado", f"{veh['tipo']} ({veh['naturaleza']})")
    with c[1]:
        tarjeta("Color · ciudad", f"{veh['color']} · {veh['ciudad']}")
        st.write("")
        tarjeta("Servicio", veh["servicio"])
