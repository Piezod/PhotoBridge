# PhotoBridge

PhotoBridge es una aplicación local para conectar de forma manual con Synology
DSM, explorar la biblioteca Synology Photos (si está disponible) o File Station
y descargar fotografías originales a este equipo. No conecta a NAS
automáticamente, no escribe ni elimina archivos remotos y no migra contenido a
Amazon Photos.

## Requisitos e instalación

- Windows y Python 3.12.
- Desde PowerShell, en la carpeta del proyecto:

```powershell
.\scripts\setup.ps1
```

El script crea `.venv` e instala la aplicación y sus dependencias de desarrollo.

## Arranque

```powershell
.\scripts\start.ps1
```

Abre <http://localhost:8000>. El servidor escucha exclusivamente en
`127.0.0.1`; para detenerlo, pulsa `Ctrl+C`. Arranque directo equivalente:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si el puerto 8000 ya está ocupado, usa temporalmente el puerto 8001:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

`GET /health` devuelve HTTP 200 y `{"status":"ok"}`.

## Conexión y uso

1. Abre **Conexiones** e introduce un nombre, URL QuickConnect, DSM/DDNS o VPN,
   usuario y contraseña. Por ejemplo, QuickConnect acepta el formato
   `https://quickconnect.to/<ID>`. La aplicación verifica TLS y, para resolver
   el alias, solo sigue redirecciones HTTPS hacia dominios QuickConnect
   (`quickconnect.to`, `quickconnect.cn` y sus subdominios). Redirecciones a
   otros dominios se rechazan.
2. Pulsa **Probar conexión**. PhotoBridge resuelve el alias sin credenciales,
   consulta `SYNO.API.Info` y comprueba la presencia de las APIs de
   autenticación, listado y descarga antes de enviar el usuario/contraseña.
   Solo entonces intenta `SYNO.API.Auth` y el permiso de lectura. Si DSM
   solicita MFA, introduce el código manualmente. También se mantienen las
   conexiones directas por IP, DDNS y VPN.
3. Las contraseñas solo se guardan si se marca la opción correspondiente y
   quedan en el almacén seguro del sistema (keyring). Las sesiones DSM se
   mantienen en memoria del servidor, nunca se envían al navegador.
4. En **Explorador**, PhotoBridge prefiere la biblioteca indexada de Synology
   Photos cuando su API y el acceso de lectura están disponibles. Puedes
   cambiar al explorador clásico **File Station**. Photos permite navegar el
   espacio personal y, si está autorizado, el compartido; usa páginas de hasta
   50 elementos y no realiza escaneos recursivos. Sus filtros de nombre,
   extensión y fecha se aplican en la página consultada, no recorren toda la
   biblioteca.
5. En Photos, busca y selecciona un álbum por su identificador. La búsqueda
   consulta hasta 1000 álbumes; también puedes paginar el selector. Selecciona
   fotografías individuales o las visibles (máximo 10), o limpia la selección.
   Pulsa **Revisar fotografías seleccionadas** para ver nombres, tamaño y
   destino; después confirma y pulsa **Descargar fotografías seleccionadas**.
   No se descargan originales al navegar ni se implementa descarga de vídeos.
   El backend
   aplica el modo de prueba obligatorio: máximo 10 fotografías, 250 MB
   (250.000.000 bytes) por operación y una descarga simultánea.

Las descargas File Station se escriben por streaming en
`data/downloads/<id_conexion>/<ruta_remota>/`. Synology Photos no expone aquí
una ruta física inequívoca; sus álbumes virtuales se descargan en
`data/downloads/<nombre_album>/<nombre_archivo>`, con nombres saneados.
El informe JSON de cada operación se guarda bajo
`data/downloads/<id_conexion>/.reports/`. Se conservan las descargas
completadas y todos los `.part`, incluso tras un error o cancelación; no se
eliminan temporales automáticamente. Los destinos existentes se omiten y se
notifican; no se sobrescriben. El SHA-256 calculado
identifica los bytes locales, pero no demuestra igualdad criptográfica con el
origen porque no se obtiene un hash remoto comparable.

## Synology Photos: APIs y validación

PhotoBridge descubre dinámicamente las rutas y versiones mediante
`SYNO.API.Info` y puede utilizar `SYNO.Foto.Browse.Item`,
`SYNO.Foto.Browse.Folder`, `SYNO.Foto.Browse.Album`,
`SYNO.Foto.Thumbnail`, `SYNO.Foto.Download` y sus APIs `SYNO.FotoTeam.*`
cuando el NAS las anuncia y las operaciones de lectura funcionan. La sesión,
cookie y `X-Syno-Token` quedan en el backend; no se devuelven al navegador.
Las miniaturas se solicitan al NAS, no se generan descargando originales.

**Limitación importante:** Synology no publica una guía oficial de API web para
Synology Photos. Estas interfaces son internas/no documentadas y se apoyan en
referencias comunitarias; pueden cambiar entre versiones DSM. Descubrir un
nombre con `SYNO.API.Info` no demuestra compatibilidad de sus métodos.
El usuario confirmó conexión, fotografías reales, miniaturas y apertura XL.
Álbumes, filtros y descarga original siguen pendientes de validación manual.
El contrato de descarga se investigó en la interfaz oficial, sin transferir
originales. La primera descarga la realiza el usuario: verificar archivo,
tamaño, destino y el informe local.

El usuario sí confirmó previamente una conexión QuickConnect real con
autenticación DSM, descubrimiento de APIs File Station, permiso de lectura y
disponibilidad de sus APIs de descarga/miniaturas (3515 ms). Esa evidencia no
valida una descarga real ni Synology Photos.

## Configuración

Los valores seguros por defecto se definen en `app/config.py`. `.env.example`
documenta las opciones locales, incluida la carpeta de descargas y una CA
adicional de confianza (`PHOTOBRIDGE_SYNOLOGY_CA_BUNDLE`). No guardes
contraseñas en `.env`; usa keyring o introdúcelas al conectar. Nunca desactives
la verificación TLS para resolver un error de certificado.

Para precargar los campos editables de conexión, configura
`PHOTOBRIDGE_SYNOLOGY_DEFAULT_NAME`, `PHOTOBRIDGE_SYNOLOGY_DEFAULT_SERVER_URL`
y `PHOTOBRIDGE_SYNOLOGY_DEFAULT_USERNAME` en el archivo local `.env`, excluido
de Git. La contraseña no se precarga; la conexión sigue siendo manual y MFA
puede solicitarse si el NAS lo requiere.

## Pruebas y lint

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Las pruebas usan mocks HTTP y no conectan con un NAS real. QuickConnect ya fue
confirmado manualmente para las capacidades indicadas arriba; las pruebas
automatizadas no reproducen esa conexión. Synology Photos, sus permisos,
miniaturas y descarga de originales siguen pendientes de validación manual.

### Repetir la validación de QuickConnect

1. Arranca PhotoBridge y abre **Conexiones**.
2. Introduce `https://quickconnect.to/<ID>` (sustituye `<ID>` por tu QuickConnect
   ID), el usuario DSM y la contraseña. No hace falta introducir de antemano el
   hostname regional.
3. Pulsa **Probar conexión**. La aplicación resuelve la redirección y confirma
   `SYNO.API.Info` y las APIs necesarias antes de autenticar. Acepta MFA solo
   introduciendo el código manualmente en la interfaz.
4. Comprueba que muestra el endpoint regional resuelto, autenticación correcta
   y permisos de lectura. Explora una carpeta autorizada y, si procede,
   descarga manualmente una única foto de prueba.
5. Si el endpoint regional devuelve HTML, no anuncia las APIs requeridas o no
   permite File Station, usa la URL DSM/DDNS o VPN directa. No desactives TLS.

La validación manual previa confirmó la conexión, autenticación, descubrimiento
de APIs y lectura (3515 ms). Las pruebas locales no prueban conectividad ni
compatibilidad de relay; la descarga de un original y Synology Photos requieren
validación aparte.

## Tecnologías y arquitectura

Python 3.12, FastAPI/Uvicorn, HTTPX, Jinja2, HTMX y Bootstrap 5 local, Pydantic
Settings, keyring, pytest y Ruff. El monolito modular separa dominio,
aplicación, infraestructura y presentación. Los recursos de la interfaz se
sirven localmente, sin CDN.

Consulta [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para los límites y
decisiones, [docs/ROADMAP.md](docs/ROADMAP.md) para los criterios por fase y
[docs/PROGRESS.md](docs/PROGRESS.md) para el historial y la validación detallada.
La decisión y el análisis de las API internas están en
[docs/adr/0004-synology-photos-adapter.md](docs/adr/0004-synology-photos-adapter.md).

Documentación oficial consultada:

- [Synology File Station API Guide](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf)
- [DSM Login Web API Guide](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Login_Web_API_Guide_enu.pdf)
- [Synology Photos API — referencias comunitarias no oficiales](https://github.com/zeichensatz/SynologyPhotosAPI)
- [N4S4 Synology API — documentación comunitaria](https://github.com/N4S4/synology-api)
