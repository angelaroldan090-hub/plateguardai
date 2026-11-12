"""Configuración central del sistema PlateGuardAI (detección de placas + alertas)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Bogota")  # hora oficial para pico y placa y fechas mostradas

BASE_DIR = Path(__file__).resolve().parent.parent

# Modo nube: Streamlit Community Cloud monta el repositorio en /mount/src.
# En la nube el scraping se desactiva (no hay pantalla para iniciar sesión ni resolver CAPTCHAs).
MODO_NUBE = os.environ.get("PLATEGUARD_MODO") == "nube" or str(BASE_DIR).startswith("/mount/src")
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "plateguardai.db"
DATASET_DIR = DATA_DIR / "reto_placas"          # aquí van set1..set4 del Drive
MODELS_DIR = BASE_DIR / "models"
SCRAPER_PROFILE_DIR = DATA_DIR / "browser_profile"  # perfil persistente del navegador del scraper
SESION_FILE = DATA_DIR / "browser_profile" / "sesion.json"  # cookies de sesión guardadas (incluye las de sesión)



def db_url() -> str | None:
    """URL de la base de datos en la nube (PostgreSQL). None -> SQLite local.
    Orden: variable de entorno DATABASE_URL -> secrets de Streamlit [db] url -> .streamlit/secrets.toml."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        import streamlit as st
        return st.secrets["db"]["url"]
    except Exception:
        pass
    archivo = BASE_DIR / ".streamlit" / "secrets.toml"
    if archivo.exists():
        import tomllib
        try:
            return tomllib.loads(archivo.read_text(encoding="utf-8")).get("db", {}).get("url")
        except Exception:
            return None
    return None


def _secreto(seccion: str, clave: str) -> str | None:
    try:
        import streamlit as st
        return st.secrets[seccion][clave]
    except Exception:
        pass
    archivo = BASE_DIR / ".streamlit" / "secrets.toml"
    if archivo.exists():
        import tomllib
        try:
            return tomllib.loads(archivo.read_text(encoding="utf-8")).get(seccion, {}).get(clave)
        except Exception:
            return None
    return None


def credenciales_medellin() -> tuple[str, str] | None:
    """Cuenta del portal de Movilidad Medellín para el inicio de sesión automático del nodo.
    Se lee de variables de entorno o de .streamlit/secrets.toml [medellin] (archivo local, no se sube a GitHub)."""
    u = os.environ.get("MEDELLIN_USUARIO") or _secreto("medellin", "usuario")
    c = os.environ.get("MEDELLIN_CLAVE") or _secreto("medellin", "clave")
    return (u, c) if u and c else None


for d in (DATA_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Clases del dataset (segmentación pedida: naturaleza de la placa x tipo de vehículo)
# ---------------------------------------------------------------------------
CLASES_VEHICULO = [
    "nacional_carro",
    "nacional_moto",
    "internacional_carro",
    "internacional_moto",
]

# ---------------------------------------------------------------------------
# Cinco categorías de alerta (cubren los 6 criterios del reto)
# ---------------------------------------------------------------------------
CATEGORIAS_ALERTA = {
    "NORMAL": {
        "nivel": 0, "color": "#2E7D32", "codigo": "N0",
        "titulo": "Sin alertas",
        "descripcion": "Vehículo verificado: no registra novedades en las fuentes consultadas.",
        "protocolo": "Continuar. No es necesario detener el vehículo.",
    },
    # No es "sin alertas": la placa no está en la base y ninguna fuente en línea respondió.
    # El sistema NO pudo verificar el vehículo y no debe decir "continuar".
    "SIN_REGISTRO": {
        "nivel": 1, "color": "#5F6B7A", "codigo": "SR1",
        "titulo": "Sin información del vehículo",
        "descripcion": "La placa no está en la base de datos y no hubo respuesta de las fuentes en línea. "
                       "El vehículo NO fue verificado.",
        "protocolo": "No asumir que está en regla. Verificar la placa y solicitar documentos; consultar a la central.",
    },
    "MULTAS_DEUDA": {
        "nivel": 1, "color": "#A16207", "codigo": "MD1",
        "titulo": "Deuda, multas o sanciones",
        "descripcion": "Comparendos/multas pendientes o sanciones que exigen inmovilización.",
        "protocolo": "Detención de rutina. Verificar si la sanción exige inmovilización.",
    },
    "DOCUMENTOS_VENCIDOS": {
        "nivel": 1, "color": "#C2410C", "codigo": "DV1",
        "titulo": "Documentos vencidos",
        "descripcion": "SOAT, revisión técnico-mecánica u otros documentos vencidos.",
        "protocolo": "Detención de rutina y verificación documental.",
    },
    "CLONACION": {
        "nivel": 2, "color": "#5B3E96", "codigo": "CL2",
        "titulo": "Posible placa clonada",
        "descripcion": "Las características observadas no coinciden con el registro de la placa.",
        "protocolo": "Precaución. Verificar número de chasis/motor con apoyo de otra unidad.",
    },
    "ACTO_ILEGAL": {
        "nivel": 3, "color": "#B91C1C", "codigo": "AI3",
        "titulo": "Vehículo reportado en acto ilegal",
        "descripcion": "Reportado por hurto, uso en delitos o participación en eventos ilegales.",
        "protocolo": "NO abordar en solitario. Reportar a central y solicitar apoyo.",
    },
}

# Restricción informativa adicional (criterio "pico y placa" del reto)
# Medellín y Valle de Aburrá, 2º semestre 2026 (vigente 3-ago-2026 a 29-ene-2027).
# Carros: último dígito. Motos: primer dígito. Horario 5:00 a 20:00, lunes a viernes.
PICO_Y_PLACA = {
    "ciudad": "Medellín / Valle de Aburrá",
    "vigencia": "2026-08-03 a 2027-01-29",
    "hora_inicio": 5,
    "hora_fin": 20,
    "dias": {0: [5, 8], 1: [1, 4], 2: [0, 2], 3: [3, 6], 4: [7, 9]},  # 0 = lunes
}

# ---------------------------------------------------------------------------
# Formatos de placa (regex). Colombia:
#   carro particular/público: ABC123
#   moto (actual):            ABC12D
#   moto (antigua):           ABC12
# Algunos formatos internacionales frecuentes en la región:
# ---------------------------------------------------------------------------
FORMATOS_PLACA = {
    "nacional_carro": [r"^[A-Z]{3}\d{3}$"],
    "nacional_moto": [r"^[A-Z]{3}\d{2}[A-Z]$", r"^[A-Z]{3}\d{2}$"],
    "internacional_carro": [
        r"^[A-Z]{3}\d{4}$",        # Ecuador (ABC1234)
        r"^[A-Z]{2}\d{3}[A-Z]{2}$",  # Venezuela / Mercosur Argentina (AB123CD)
        r"^[A-Z]{3}\d[A-Z]\d{2}$",   # Mercosur Brasil (ABC1D23)
        r"^[A-Z]\d{2}[A-Z]{3}$",     # Venezuela antigua
        r"^[A-Z0-9]{5,8}$",          # genérico (EE.UU., Europa, etc.)
    ],
    "internacional_moto": [r"^[A-Z]{2}\d{3}[A-Z]$", r"^\d{3}[A-Z]{3}$"],
}

# Colores de fondo de placa en Colombia (para la naturaleza/servicio)
COLORES_PLACA_CO = {
    "amarillo": "Particular",
    "blanco": "Servicio público",
    "azul": "Diplomático",
    "rojo": "Transitorio / importación",
    "verde": "Zona de frontera / otros",
}

# Lectura de la placa: por debajo de esta confianza del OCR se pide confirmación al agente
UMBRAL_CONFIANZA_OCR = 0.55
# Correcciones de caracteres (O->0, 6->G…) a partir de las cuales la lectura se considera dudosa
MAX_CORRECCIONES_OCR = 1

# Ley 1581 de 2012 (Habeas Data): minimizar datos personales en el historial
ANONIMIZAR_HISTORIAL_POR_DEFECTO = True
