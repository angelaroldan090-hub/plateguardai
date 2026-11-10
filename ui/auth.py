"""Inicio de sesión simple para la versión publicada en la web.

Las credenciales se definen en los *secrets* de Streamlit (nunca en el código):
    [auth]
    usuario = "..."
    clave = "..."
Si no hay secrets configurados (uso local), no se pide inicio de sesión.
"""
import hmac

import streamlit as st

from . import componentes as ui


def _credenciales():
    try:
        a = st.secrets["auth"]
        return a["usuario"], a["clave"]
    except Exception:
        return None


def requerir_login():
    cred = _credenciales()
    if cred is None or st.session_state.get("autenticado"):
        return
    st.markdown("""<style>[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] { display:none; }</style>""", unsafe_allow_html=True)
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.markdown(f"""
        <div class="login-cab">
          <img src="data:image/png;base64,{ui.logo_b64()}">
          <div class="nombre">PlateGuard<span>AI</span></div>
          <div class="sub">Verificación vehicular inteligente</div>
        </div>""", unsafe_allow_html=True)
        with st.form("login"):
            st.markdown("**Acceso restringido**")
            u = st.text_input("Usuario")
            c = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                ok_u = hmac.compare_digest(u.strip(), cred[0])
                ok_c = hmac.compare_digest(c, cred[1])
                if ok_u and ok_c:
                    st.session_state["autenticado"] = True
                    st.rerun()
                st.error("Usuario o contraseña incorrectos.")
        st.caption("Uso exclusivo de personal autorizado. Tratamiento de datos conforme a la Ley 1581 de 2012.")
    st.stop()


def boton_salir():
    if _credenciales() and st.session_state.get("autenticado"):
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.clear()
            st.rerun()
