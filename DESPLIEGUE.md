# Publicar PlateGuardAI en la web con scraping real

## Cómo funciona

```
 Celular / navegador                 Nube                          Su computador
┌──────────────────┐   ┌──────────────────────────────┐   ┌───────────────────────────┐
│ App web          │──▶│ Base de datos (Supabase)     │◀──│ Nodo de scraping          │
│ (Streamlit Cloud)│◀──│ registros · resultados ·     │──▶│ python nodo_scraping.py   │
│ pide consultas   │   │ cola de solicitudes          │   │ abre SIMIT / Medellín     │
└──────────────────┘   └──────────────────────────────┘   └───────────────────────────┘
```

1. Desde el celular se escanea o escribe una placa y se marcan las fuentes en línea (SIMIT, Medellín).
2. La app web deja una **solicitud** en la base de datos.
3. El **nodo** (su computador) la toma, abre el portal en un navegador real (donde usted inició sesión
   o resuelve el CAPTCHA), extrae el resultado y lo guarda en la base de datos.
4. En el celular se pulsa **Actualizar resultados en línea** y la alerta se recalcula con esos datos.

El scraping se hace en su computador porque los portales exigen iniciar sesión o resolver CAPTCHA,
y un servidor en la nube no tiene pantalla para eso.

Todo es gratis. Tiempo aproximado: 30 minutos.

---

## Paso 1 · Crear la base de datos en Supabase

1. Entre a https://supabase.com → **Start your project** → inicie sesión (puede usar su cuenta de GitHub).
2. **New project**:
   - Name: `plateguardai`
   - Database Password: invente una **solo con letras y números** (sin símbolos) y guárdela.
   - Region: la más cercana (por ejemplo *East US*).
   - **Create new project** (tarda 1–2 minutos).
3. Arriba pulse **Connect**. En *Connection String* elija **Session pooler** y copie la URL. Se ve así:
   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
4. Reemplace `[YOUR-PASSWORD]` por su contraseña (sin corchetes). Esa es su **URL de base de datos**.
   Trátela como una contraseña: no la comparta ni la publique.

> Use la opción **Session pooler** (no "Direct connection"): Streamlit Cloud solo funciona con esa.
> Las tablas se crean solas la primera vez que la app o el nodo se conectan.

## Paso 2 · Subir el proyecto a GitHub

1. Cree una cuenta en https://github.com (si no tiene) → **+ → New repository**.
   - Repository name: `plateguardai` · marque **Private** · **Create repository**.
2. Pulse **uploading an existing file** y arrastre **el contenido** de la carpeta `plateguardai`
   (`app.py`, `nodo_scraping.py`, `core`, `ui`, `assets`, `data`, `.streamlit`, etc.).
   - `.streamlit` es una carpeta oculta. Windows: Explorador → Vista → Mostrar → Elementos ocultos.
   - **No suba** `.venv`, `data/reto_placas` ni ningún archivo `secrets.toml`.
3. **Commit changes**.

## Paso 3 · Publicar la app web

1. Entre a https://share.streamlit.io con su cuenta de GitHub → **Create app** → *Deploy from repository*.
2. Repository `su_usuario/plateguardai` · Branch `main` · Main file path `app.py` · App URL: `plateguardai`.
3. **Advanced settings**:
   - Python version: **3.11**
   - **Secrets** (cambie los valores):
     ```
     [auth]
     usuario = "su_usuario"
     clave = "una_clave_segura"

     [db]
     url = "postgresql://postgres.abcdefgh:SUCLAVE@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
     ```
4. **Deploy**. En el menú lateral de la app debe aparecer **Base de datos: PostgreSQL en la nube**.

## Paso 4 · Preparar el nodo de scraping en su computador

(Requiere haber hecho la instalación local del README: entorno `.venv`, `pip install -r requirements-local.txt`
y `playwright install chromium`.)

1. En la carpeta del proyecto, dentro de `.streamlit`, cree un archivo llamado `secrets.toml` con:
   ```
   [db]
   url = "postgresql://postgres.abcdefgh:SUCLAVE@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
   ```
   (la misma URL del paso 1; **este archivo nunca se sube a GitHub**).
2. Inicie sesión en el portal de Movilidad Medellín (una sola vez; la sesión queda guardada):
   ```
   .venv\Scripts\activate
   python nodo_scraping.py --login
   ```
   Se abre una ventana de Chrome: ingrese con su cuenta del portal. Tiene 3 minutos.
   (El scraper usa su propia ventana; la sesión de su navegador normal no le sirve.)
   La consulta que se automatiza es **Trámites y servicios → Consultas → Estado del vehículo**.
3. **Primera prueba real** (verifique que los portales se leen bien):
   ```
   python nodo_scraping.py --placas EGX799 --fuentes simit,medellin
   ```
   Se abre Chrome, llena la placa y busca. En SIMIT puede aparecer una verificación anti-robots:
   complétela en la ventana. En la terminal se imprime lo que se leyó (resumen de SIMIT y la tabla
   Concepto/Estado de Medellín). Si dice "No se pudo leer", copie lo que imprime y envíelo para ajustar.
4. Encienda el nodo y **deje la ventana de la terminal abierta** durante la demostración:
   ```
   python nodo_scraping.py
   ```
   Debe decir `conectado a: PostgreSQL en la nube` y `Esperando solicitudes…`.

## Paso 5 · Probar desde el celular

1. Abra el link de la app (por ejemplo `https://plateguardai.streamlit.app`) e ingrese.
2. Toque `>>` para abrir el menú: debe decir **Nodo de scraping: en línea**.
3. En **Fuentes** marque *SIMIT* y/o *Movilidad Medellín*.
4. **Verificación en campo → Cámara** (permita el acceso; cambie a la cámara trasera) → apunte a la
   placa → **Analizar vehículo**. O use **Consulta por placa**.
5. En la pestaña **Fuentes en línea** verá la consulta *PENDIENTE*. En la terminal del computador
   aparece `Solicitud #… : PLACA en SIMIT` y se abre el navegador. Si sale un CAPTCHA, resuélvalo ahí.
6. Pulse **Actualizar resultados en línea**: la alerta se recalcula con lo que trajo el portal.

## Scraping 100 % automático

- **SIMIT:** el nodo abre el portal, escribe la placa y hace clic en la lupa (botón *Realizar consulta*).
- **Movilidad Medellín:** para que el nodo inicie sesión solo cuando la sesión vence, agregue su cuenta
  del portal al archivo local `.streamlit/secrets.toml` (no se sube a GitHub):
  ```
  [medellin]
  usuario = "su_usuario_del_portal"
  clave = "su_clave_del_portal"
  ```
  El nodo guarda la sesión y la revisa cada 20 minutos; si vence, vuelve a ingresar solo.
  Sin esta sección, ejecute `python nodo_scraping.py --login` cuando la terminal avise que la sesión venció.
- **Desde la cámara:** SIMIT y Movilidad Medellín vienen marcados por defecto; cada placa leída se
  consulta sola. En la web, la consulta queda en cola, el nodo la resuelve y la app muestra el
  resultado automáticamente (espera hasta 90 s, sin pulsar nada).

## Ingesta continua (cada 2 horas como máximo)

El nodo no solo responde a las consultas de la web: cada 2 horas vuelve a consultar en SIMIT y
Movilidad Medellín **todas las placas de la lista de seguimiento** y actualiza la base de datos.
Así la información nunca tiene más de 2 horas.

1. **Agregar placas al seguimiento** (solo placas autorizadas, Ley 1581): en la app,
   *Base de datos y scraping → Ingesta continua → Agregar placa al seguimiento*, o en la terminal:
   ```
   python nodo_scraping.py --seguir EGX799,ABC123
   ```
2. **Encender el nodo**: doble clic en `iniciar_nodo.bat` (activa el entorno, arranca el nodo y
   lo reinicia solo si se cae). La primera ingesta se hace al arrancar y luego cada 2 horas.
   Para un intervalo más corto: `python nodo_scraping.py --cada 60` (mínimo 15, máximo 120 minutos).
3. **Que arranque solo al encender el computador** (opcional). En una terminal **como administrador**:
   ```
   schtasks /Create /TN "PlateGuardAI nodo" /TR "C:\Users\User\Documents\plateguardai\iniciar_nodo.bat" /SC ONLOGON /RL LIMITED
   ```
   Para quitarlo: `schtasks /Delete /TN "PlateGuardAI nodo" /F`
4. **Evite que el computador se suspenda** mientras el nodo trabaja: Configuración → Sistema →
   Inicio/apagado y suspensión → "Suspender" en **Nunca** (al menos cuando esté conectado).
5. En la app, *Base de datos y scraping* muestra las placas en seguimiento, la última ingesta,
   las consultas desactualizadas (más de 2 h) y el historial de ingestas.

### Consultas por adelantado (recomendado antes de presentar)

Para no depender del tiempo de respuesta de los portales durante la presentación, consulte antes
las placas que va a mostrar; los resultados quedan vigentes 2 h y salen al instante:
```
python nodo_scraping.py --placas EGX799,KTM123 --fuentes simit,medellin
```

## Placas para la demostración

Imprima `data/demo/hoja_placas_demo.pdf` (o muéstrela en otra pantalla) y apunte la cámara a una placa
a la vez:

| Placa | Resultado esperado (base de datos de prueba) |
|---|---|
| LUZ482 | N0 · Sin alertas |
| KTM123 | MD1 · Multas pendientes |
| HJK321 | DV1 · Documentos vencidos |
| EGX799 | CL2 · Posible clonación |
| MNB654 | AI3 · Reportado por hurto (protocolo: no abordar en solitario) |
| ABC12D | AI3 · Moto usada en delito |

Para el scraping real use placas que usted esté autorizada a consultar (por ejemplo un vehículo propio
o la placa de ejemplo del profesor), en cumplimiento de la Ley 1581 de 2012.

## Notas

- Si el nodo está apagado, la app web sigue funcionando con la base de datos; las solicitudes quedan
  en cola y se atienden cuando el nodo se encienda.
- Si la app pasa varios días sin uso, Streamlit la "duerme": ábrala unos minutos antes de presentar.
  Supabase también pausa proyectos gratuitos tras 7 días sin actividad (se reactivan desde su panel).
- RUNT no se usa en la cola automática: exige el documento del propietario además del CAPTCHA.
- Para actualizar la app, suba los archivos modificados al repositorio (sin `secrets.toml`).
