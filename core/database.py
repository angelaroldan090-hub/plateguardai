"""Base de datos del sistema: registros de vehículos, documentos, multas, reportes,
resultados de scraping, cola de solicitudes al nodo de scraping e historial.

Motor:
  * PostgreSQL en la nube (Supabase, Neon…) si hay una URL configurada  -> la comparten
    la app web y el nodo de scraping del computador local.
  * SQLite local (data/plateguardai.db) si no hay URL.
La URL se toma de: variable de entorno DATABASE_URL, o secrets de Streamlit [db] url.
"""
from __future__ import annotations

import hashlib
import json
import random
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import sqlalchemy as sa

from .config import DB_PATH, ZONA, db_url

_ENGINE = None


def motor() -> sa.Engine:
    global _ENGINE
    if _ENGINE is None:
        url = db_url()
        if url:
            url = url.replace("postgres://", "postgresql://", 1)
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            _ENGINE = sa.create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2)
        else:
            _ENGINE = sa.create_engine(f"sqlite:///{DB_PATH}")
    return _ENGINE


def es_nube() -> bool:
    return motor().dialect.name == "postgresql"


def descripcion_motor() -> str:
    return "PostgreSQL en la nube" if es_nube() else "SQLite local"


@contextmanager
def conexion():
    with motor().begin() as con:
        yield con


def _q(con, sql, params=None):
    return con.execute(sa.text(sql), params or {})


def _filas(res) -> list[dict]:
    return [dict(r._mapping) for r in res]


ESQUEMA = """
CREATE TABLE IF NOT EXISTS vehiculos (
    placa TEXT PRIMARY KEY, naturaleza TEXT, tipo TEXT, servicio TEXT,
    marca TEXT, linea TEXT, modelo INTEGER, color TEXT, ciudad TEXT
);
CREATE TABLE IF NOT EXISTS documentos (
    id {AUTO}, placa TEXT, documento TEXT, vence TEXT
);
CREATE TABLE IF NOT EXISTS multas (
    id {AUTO}, placa TEXT, codigo TEXT, descripcion TEXT,
    valor REAL, fecha TEXT, estado TEXT, inmoviliza INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reportes (
    id {AUTO}, placa TEXT, tipo TEXT, descripcion TEXT,
    fecha TEXT, fuente TEXT, activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS cache_scraping (
    placa TEXT, fuente TEXT, fecha TEXT, datos TEXT, PRIMARY KEY (placa, fuente)
);
CREATE TABLE IF NOT EXISTS solicitudes (
    id {AUTO}, placa TEXT, fuente TEXT, estado TEXT, creada TEXT, atendida TEXT, mensaje TEXT
);
CREATE TABLE IF NOT EXISTS nodos (
    nombre TEXT PRIMARY KEY, ultimo_latido TEXT, info TEXT
);
CREATE TABLE IF NOT EXISTS seguimiento (
    placa TEXT PRIMARY KEY, fuentes TEXT, motivo TEXT, agregada TEXT, activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS ingestas (
    id {AUTO}, nodo TEXT, inicio TEXT, fin TEXT, placas INTEGER, consultas_ok INTEGER,
    consultas_error INTEGER, estado TEXT
);
CREATE TABLE IF NOT EXISTS consultas (
    id {AUTO}, fecha TEXT, placa TEXT, clase TEXT,
    categoria TEXT, nivel INTEGER, fuentes TEXT, origen TEXT
);
"""

_INICIALIZADA = False


def inicializar():
    global _INICIALIZADA
    if _INICIALIZADA:
        return
    auto = "SERIAL PRIMARY KEY" if es_nube() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with conexion() as con:
        for stmt in ESQUEMA.replace("{AUTO}", auto).split(";"):
            if stmt.strip():
                _q(con, stmt)
        if _q(con, "SELECT COUNT(*) FROM vehiculos").scalar() == 0:
            _sembrar(con)
    _INICIALIZADA = True


def _ahora() -> str:
    """Marca de tiempo en UTC (el servidor web y el nodo local pueden estar en zonas distintas)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _leer_fecha(txt: str) -> datetime:
    dt = datetime.fromisoformat(txt)
    return dt if dt.tzinfo else dt.replace(tzinfo=ZONA)


def hora_local(dt: datetime) -> str:
    return dt.astimezone(ZONA).strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# Datos de ejemplo (sintéticos) que cubren las 5 categorías de alerta
# ---------------------------------------------------------------------------
def _sembrar(con):
    hoy = datetime.now(ZONA).date()
    cols = ["placa", "naturaleza", "tipo", "servicio", "marca", "linea", "modelo", "color", "ciudad"]
    vehiculos = [
        ("EGX799", "nacional", "carro", "Particular", "Chevrolet", "Spark GT", 2016, "Rojo", "Medellín"),
        ("KTM123", "nacional", "carro", "Particular", "Renault", "Logan", 2019, "Gris", "Bogotá"),
        ("ABC12D", "nacional", "moto", "Particular", "Yamaha", "NMAX", 2022, "Negro", "Medellín"),
        ("WPN456", "nacional", "carro", "Servicio público", "Hyundai", "Atos", 2014, "Amarillo", "Medellín"),
        ("FRT88K", "nacional", "moto", "Particular", "AKT", "NKD 125", 2020, "Azul", "Envigado"),
        ("HJK321", "nacional", "carro", "Particular", "Mazda", "3", 2021, "Blanco", "Itagüí"),
        ("ZXC45A", "nacional", "moto", "Particular", "Bajaj", "Pulsar NS", 2023, "Rojo", "Bello"),
        ("PCD7841", "internacional", "carro", "Particular (EC)", "Kia", "Rio", 2018, "Plata", "Quito"),
        ("MNB654", "nacional", "carro", "Particular", "Toyota", "Hilux", 2020, "Blanco", "Rionegro"),
        ("QWE90B", "nacional", "moto", "Particular", "Honda", "CB 190", 2021, "Negro", "Medellín"),
        ("LUZ482", "nacional", "carro", "Particular", "Kia", "Picanto", 2022, "Gris", "Medellín"),
    ]
    _q(con, f"INSERT INTO vehiculos ({','.join(cols)}) VALUES ({','.join(':' + c for c in cols)})",
       [dict(zip(cols, v)) for v in vehiculos])

    def f(d):
        return (hoy + timedelta(days=d)).isoformat()

    docs = []
    for v in vehiculos:
        docs += [(v[0], "SOAT", f(random.randint(60, 300))), (v[0], "Revisión técnico-mecánica", f(random.randint(60, 300)))]
    docs += [("HJK321", "SOAT", f(-25)), ("FRT88K", "Revisión técnico-mecánica", f(-90))]
    _q(con, "INSERT INTO documentos (placa, documento, vence) VALUES (:p, :d, :v)",
       [{"p": a, "d": b, "v": c} for a, b, c in docs])

    multas = [
        ("KTM123", "C29", "Conducir a velocidad superior a la máxima permitida", 604200, f(-120), "Pendiente", 0),
        ("KTM123", "C14", "Transitar en horario de pico y placa", 604200, f(-40), "Pendiente", 0),
        ("ZXC45A", "D12", "Conducir sin portar licencia / vehículo inmovilizable", 1208400, f(-15), "Pendiente", 1),
        ("WPN456", "C02", "Estacionar en sitio prohibido", 604200, f(-400), "Pagada", 0),
    ]
    mc = ["placa", "codigo", "descripcion", "valor", "fecha", "estado", "inmoviliza"]
    _q(con, f"INSERT INTO multas ({','.join(mc)}) VALUES ({','.join(':' + c for c in mc)})",
       [dict(zip(mc, m)) for m in multas])

    reportes = [
        ("MNB654", "hurto", "Vehículo reportado como hurtado", f(-10), "Base local (simulada)", 1),
        ("ABC12D", "delito", "Moto usada en hurto a mano armada (registro simulado)", f(-5), "Base local (simulada)", 1),
        ("QWE90B", "evento_ilegal", "Participación en piques ilegales (registro simulado)", f(-30), "Base local (simulada)", 1),
        ("EGX799", "clonacion", "Placa reportada en dos vehículos distintos (registro simulado)", f(-3), "Base local (simulada)", 1),
    ]
    rc = ["placa", "tipo", "descripcion", "fecha", "fuente", "activo"]
    _q(con, f"INSERT INTO reportes ({','.join(rc)}) VALUES ({','.join(':' + c for c in rc)})",
       [dict(zip(rc, r)) for r in reportes])


# ---------------------------------------------------------------------------
# Consultas de registros
# ---------------------------------------------------------------------------
def registro_completo(placa: str) -> dict:
    with conexion() as con:
        v = _filas(_q(con, "SELECT * FROM vehiculos WHERE placa=:p", {"p": placa}))
        docs = _filas(_q(con, "SELECT documento, vence FROM documentos WHERE placa=:p", {"p": placa}))
        multas = _filas(_q(con, "SELECT codigo, descripcion, valor, fecha, estado, inmoviliza FROM multas WHERE placa=:p",
                           {"p": placa}))
        reps = _filas(_q(con, "SELECT tipo, descripcion, fecha, fuente FROM reportes WHERE placa=:p AND activo=1",
                         {"p": placa}))
    return {"vehiculo": v[0] if v else None, "documentos": docs, "multas": multas, "reportes": reps}


def _distancia(a: str, b: str) -> int:
    """Distancia de edición (sustituir, insertar o borrar un carácter)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def placas_similares(placa: str, max_dif: int = 1) -> list[str]:
    """Placas registradas a distancia de edición <= max_dif: un carácter cambiado (J/I, 0/O, 8/B)
    o uno que falta o sobra (caso MG650 -> OMG650)."""
    if not placa:
        return []
    with conexion() as con:
        todas = [r[0] for r in _q(con, "SELECT placa FROM vehiculos")]
    return [p for p in todas if p != placa and abs(len(p) - len(placa)) <= max_dif
            and _distancia(p, placa) <= max_dif]


TABLAS = {"vehiculos", "documentos", "multas", "reportes", "cache_scraping", "solicitudes", "nodos", "consultas",
          "seguimiento", "ingestas"}


def tabla(nombre: str) -> pd.DataFrame:
    if nombre not in TABLAS:
        raise ValueError(nombre)
    with conexion() as con:
        return pd.DataFrame(_filas(_q(con, f"SELECT * FROM {nombre}")))


def guardar_vehiculo(datos: dict):
    cols = list(datos)
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "placa")
    with conexion() as con:
        _q(con, f"INSERT INTO vehiculos ({','.join(cols)}) VALUES ({','.join(':' + c for c in cols)}) "
                f"ON CONFLICT (placa) DO UPDATE SET {upd}", datos)


def agregar(nombre: str, datos: dict):
    if nombre not in TABLAS:
        raise ValueError(nombre)
    cols = list(datos)
    with conexion() as con:
        _q(con, f"INSERT INTO {nombre} ({','.join(cols)}) VALUES ({','.join(':' + c for c in cols)})", datos)


# ---------------------------------------------------------------------------
# Resultados de scraping (los escribe el nodo local, los lee la app web)
# ---------------------------------------------------------------------------
def cache_get(placa: str, fuente: str):
    """Devuelve (datos, fecha) del último resultado guardado, o None."""
    with conexion() as con:
        r = _filas(_q(con, "SELECT fecha, datos FROM cache_scraping WHERE placa=:p AND fuente=:f",
                      {"p": placa, "f": fuente}))
    if not r:
        return None
    return json.loads(r[0]["datos"]), _leer_fecha(r[0]["fecha"])


def cache_set(placa: str, fuente: str, datos: dict):
    with conexion() as con:
        _q(con, "INSERT INTO cache_scraping (placa, fuente, fecha, datos) VALUES (:p, :f, :t, :d) "
                "ON CONFLICT (placa, fuente) DO UPDATE SET fecha=excluded.fecha, datos=excluded.datos",
           {"p": placa, "f": fuente, "t": _ahora(), "d": json.dumps(datos, ensure_ascii=False)})


# ---------------------------------------------------------------------------
# Cola de solicitudes: la app web pide, el nodo local de scraping atiende
# ---------------------------------------------------------------------------
def crear_solicitud(placa: str, fuente: str) -> int:
    with conexion() as con:
        ya = _q(con, "SELECT id FROM solicitudes WHERE placa=:p AND fuente=:f AND estado IN ('pendiente','en_proceso')",
                {"p": placa, "f": fuente}).scalar()
        if ya:
            return ya
        return _q(con, "INSERT INTO solicitudes (placa, fuente, estado, creada) VALUES (:p, :f, 'pendiente', :t) RETURNING id",
                  {"p": placa, "f": fuente, "t": _ahora()}).scalar()


def estado_solicitud(placa: str, fuente: str) -> dict | None:
    with conexion() as con:
        r = _filas(_q(con, "SELECT * FROM solicitudes WHERE placa=:p AND fuente=:f ORDER BY id DESC LIMIT 1",
                      {"p": placa, "f": fuente}))
    return r[0] if r else None


def tomar_solicitudes(limite: int = 5) -> list[dict]:
    with conexion() as con:
        filas = _filas(_q(con, "SELECT * FROM solicitudes WHERE estado='pendiente' ORDER BY id LIMIT :n", {"n": limite}))
        for f in filas:
            _q(con, "UPDATE solicitudes SET estado='en_proceso' WHERE id=:i", {"i": f["id"]})
    return filas


def cerrar_solicitud(id_: int, ok: bool, mensaje: str):
    with conexion() as con:
        _q(con, "UPDATE solicitudes SET estado=:e, atendida=:t, mensaje=:m WHERE id=:i",
           {"e": "completada" if ok else "error", "t": _ahora(), "m": mensaje[:300], "i": id_})


def latido_nodo(nombre: str, info: str = ""):
    with conexion() as con:
        _q(con, "INSERT INTO nodos (nombre, ultimo_latido, info) VALUES (:n, :t, :i) "
                "ON CONFLICT (nombre) DO UPDATE SET ultimo_latido=excluded.ultimo_latido, info=excluded.info",
           {"n": nombre, "t": _ahora(), "i": info})


def estado_nodos(en_linea_seg: int = 45) -> list[dict]:
    with conexion() as con:
        filas = _filas(_q(con, "SELECT * FROM nodos"))
    ahora = datetime.now(timezone.utc)
    for f in filas:
        seg = (ahora - _leer_fecha(f["ultimo_latido"])).total_seconds()
        f["hace_seg"] = int(seg)
        f["en_linea"] = seg <= en_linea_seg
    return filas


# ---------------------------------------------------------------------------
# Ingesta continua: placas en seguimiento que el nodo refresca periódicamente
# ---------------------------------------------------------------------------
def agregar_seguimiento(placa: str, fuentes: str = "simit,medellin", motivo: str = ""):
    with conexion() as con:
        _q(con, "INSERT INTO seguimiento (placa, fuentes, motivo, agregada, activo) VALUES (:p, :f, :m, :t, 1) "
                "ON CONFLICT (placa) DO UPDATE SET fuentes=excluded.fuentes, motivo=excluded.motivo, activo=1",
           {"p": placa.upper().strip(), "f": fuentes, "m": motivo, "t": _ahora()})


def quitar_seguimiento(placa: str):
    with conexion() as con:
        _q(con, "UPDATE seguimiento SET activo=0 WHERE placa=:p", {"p": placa})


def lista_seguimiento(solo_activas: bool = True) -> list[dict]:
    with conexion() as con:
        sql = "SELECT * FROM seguimiento" + (" WHERE activo=1" if solo_activas else "") + " ORDER BY placa"
        return _filas(_q(con, sql))


def pendientes_de_ingesta(horas: float) -> list[tuple[str, str]]:
    """(placa, fuente) en seguimiento cuyo último resultado es más viejo que `horas` (o no existe)."""
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    out = []
    for s in lista_seguimiento():
        for f in [x.strip() for x in (s["fuentes"] or "").split(",") if x.strip()]:
            g = cache_get(s["placa"], f)
            if g is None or g[1] < limite:
                out.append((s["placa"], f))
    return out


def iniciar_ingesta(nodo: str, n_placas: int) -> int:
    with conexion() as con:
        return _q(con, "INSERT INTO ingestas (nodo, inicio, placas, consultas_ok, consultas_error, estado) "
                       "VALUES (:n, :t, :p, 0, 0, 'en_curso') RETURNING id",
                  {"n": nodo, "t": _ahora(), "p": n_placas}).scalar()


def cerrar_ingesta(id_: int, ok: int, error: int, estado: str = "completada"):
    with conexion() as con:
        _q(con, "UPDATE ingestas SET fin=:t, consultas_ok=:o, consultas_error=:e, estado=:s WHERE id=:i",
           {"t": _ahora(), "o": ok, "e": error, "s": estado, "i": id_})


def ultimas_ingestas(n: int = 20) -> pd.DataFrame:
    with conexion() as con:
        df = pd.DataFrame(_filas(_q(con, "SELECT * FROM ingestas ORDER BY id DESC LIMIT :n", {"n": n})))
    for c in ("inicio", "fin"):
        if not df.empty:
            df[c] = df[c].map(lambda t: hora_local(_leer_fecha(t)) if t else "")
    return df


# ---------------------------------------------------------------------------
# Historial (Ley 1581 de 2012: se puede guardar la placa seudonimizada)
# ---------------------------------------------------------------------------
def seudonimizar(placa: str) -> str:
    return "H-" + hashlib.sha256(placa.encode()).hexdigest()[:10].upper()


def registrar_consulta(placa, clase, categoria, nivel, fuentes, origen, anonimizar=True):
    with conexion() as con:
        _q(con, "INSERT INTO consultas (fecha, placa, clase, categoria, nivel, fuentes, origen) "
                "VALUES (:f, :p, :c, :cat, :n, :fu, :o)",
           {"f": _ahora(), "p": seudonimizar(placa) if anonimizar else placa, "c": clase, "cat": categoria,
            "n": nivel, "fu": ",".join(fuentes), "o": origen})


def historial() -> pd.DataFrame:
    df = tabla("consultas")
    if df.empty:
        return df
    df["fecha"] = df["fecha"].map(lambda t: hora_local(_leer_fecha(t)))
    return df.sort_values("id", ascending=False)
