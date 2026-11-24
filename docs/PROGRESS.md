# Progreso de PhotoBridge

## Fase implementada

Fase 1 — Conexión manual de solo lectura con Synology, exploración paginada y
descarga controlada de fotografías. La aplicación no conecta a NAS durante el
arranque. No se ha comenzado la fase 2 ni se han implementado Amazon Photos,
Playwright, sincronización o migraciones.

## Cambios realizados

- Cliente HTTPX de Synology: descubrimiento de APIs/versiones, autenticación,
  cierre de sesión, MFA manual, listado, miniaturas anunciadas y descarga
  streaming original.
- Gestión de conexión: validación HTTPS/URL, detección QuickConnect, prueba de
  permisos de lectura, diagnóstico y credenciales opcionales mediante keyring.
- Explorador: carpetas compartidas, navegación y breadcrumbs, paginación de
  hasta 50 elementos, filtro de formatos admitidos y selección de hasta 10
  fotografías.
- Descargas: confirmación obligatoria, tope configurable de 250 MB
  (250.000.000 bytes) y una operación simultánea; staging `.part`, cálculo
  SHA-256, validación de tamaño,
  cancelación, comprobación de rutas locales y colisiones, progreso e informe
  JSON por operación.
- Interfaz en español para conexiones, explorador, selección y progreso;
  solicitudes POST protegidas mediante token CSRF. Las sesiones DSM no se
  exponen al navegador.
- Configuración, dependencias, README, arquitectura y este registro
  actualizados; decisión de integración documentada en
  `docs/adr/0002-synology-readonly-download.md`.

## Archivos creados o modificados

- Configuración/documentación: `.env.example`, `README.md`, `pyproject.toml`,
  `app/config.py`, `docs/ARCHITECTURE.md`, este archivo y ADR 0002.
- Servicios/modelos/puertos: `app/application/services/synology_connections.py`,
  `app/application/services/synology_downloads.py`,
  `app/domain/models/synology.py` y
  `app/domain/ports/credential_store.py`.
- Adaptadores: `app/infrastructure/synology/client.py` y
  `app/infrastructure/security/keyring_store.py`.
- Presentación: `app/main.py`, `app/presentation/api/routes.py`,
  `app/presentation/api/csrf.py`, `app/presentation/api/synology_routes.py`,
  `app/presentation/formatting.py`, plantillas de inicio/conexión/explorador/
  descarga, CSS y JavaScript.
- Pruebas: `tests/helpers/synology.py`,
  `tests/unit/test_synology_client.py`,
  `tests/unit/test_synology_connections.py`,
  `tests/unit/test_synology_downloads.py`,
  `tests/unit/test_formatting.py`, `tests/integration/test_synology_ui.py` y
  `tests/unit/test_config.py`.

## Decisiones técnicas

- Se consultaron las guías oficiales DSM Login y File Station. Se descubre
  `SYNO.API.Info` en tiempo de conexión y se usan las rutas/versiones
  anunciadas por el NAS; no se fijan versiones DSM.
- Las credenciales se envían por POST. La sesión/cookie DSM permanece en
  memoria del servidor; recordar contraseña es opcional y utiliza keyring.
- Solo HTTPS, verificación TLS habilitada, CA adicional configurable y
  redirecciones HTTP rechazadas. QuickConnect se detecta, pero no se asume que
  su URL resuelva el acceso directo a File Station.
- La descarga es secuencial y en streaming. No hay subida ni escritura remota.
  Los informes identifican el SHA-256 local y dejan explícito que no se ha
  verificado contra un hash remoto.
- Las operaciones no son persistentes; reiniciar la aplicación cierra las
  sesiones y no permite recuperar/reanudar descargas interrumpidas.
- HTTPX pasó de dependencia de desarrollo a dependencia de ejecución y se
  incorporó keyring. No se añadió `python-multipart`; los formularios
  URL-encoded y su token CSRF se validan sin parser multipart.

## Pruebas ejecutadas

- `.\.venv\Scripts\python.exe -m pytest -q` — **46 aprobadas, 1 omitida**.
  Pruebas simuladas con mocks HTTP; sin conexión a NAS real. La prueba omitida
  necesita crear enlaces simbólicos, operación no permitida por el Windows de
  esta sesión.
- `.\.venv\Scripts\python.exe -m ruff check .` — correcto, sin errores.
- `git diff --check` — correcto.
- Diagnóstico Pylance de espacio de trabajo — sin diagnósticos devueltos.
- Arranque real local con `.\scripts\start.ps1`: `/`, `/health`,
  `/connections` y `/static/styles.css` respondieron HTTP 200; el proceso se
  detuvo después de la comprobación. Esto no es una prueba contra un NAS.
- Validación manual previa confirmada por el usuario: QuickConnect resuelto,
  NAS real conectado, autenticación DSM, descubrimiento de APIs File Station,
  APIs de descarga/miniaturas y permisos de lectura comprobados; latencia
  observada de 3515 ms. No se afirmó ni se probó una descarga real en esa
  validación.

## Problemas pendientes y limitaciones

- Sigue pendiente validar manualmente una descarga original y su apertura. La
  conexión QuickConnect, autenticación, APIs File Station y lectura ya fueron
  confirmadas por el usuario; no extender esa evidencia a Synology Photos.
- Se debe verificar visualmente que los archivos descargados se abren y que
  el tamaño corresponde al original; el hash local no es una comparación con
  el NAS.
- No se guarda estado de operaciones ni hay recuperación después de cerrar la
  aplicación. No se deben reintentar a ciegas transferencias interrumpidas.
- La prueba de enlaces simbólicos se omitió por una limitación del entorno
  Windows; la comprobación correspondiente sí está implementada.
- Synology Photos usa APIs internas/no documentadas; sus métodos, permisos,
  miniaturas y descargas deben probarse en el NAS del usuario.

## Arranque y validación manual

Desde PowerShell, en la raíz del proyecto:

1. `.\scripts\setup.ps1`
2. `.\scripts\start.ps1`
3. Abrir `http://localhost:8000`.
4. Ir a **Conexiones** e introducir manualmente una URL HTTPS DSM/DDNS o VPN,
   usuario y contraseña; opcionalmente marcar recordar credenciales.
5. Si se solicita MFA, introducir el código manualmente y probar de nuevo.
6. Confirmar que el diagnóstico muestra autenticación y permisos de lectura.
7. Explorar una carpeta autorizada, seleccionar una fotografía y confirmar
   expresamente la descarga. Verificar el archivo en
   `data/downloads/<id_conexion>/` y el informe en `.reports/`.

Para validar localmente, sin NAS:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Las instrucciones vigentes de trabajo establecen que Copilot no debe ejecutar
esas pruebas o comprobaciones ni crear nuevas pruebas. El usuario realiza la
validación funcional y comunica cualquier error. No marcar funcionalidades
como validadas sin su confirmación explícita. Al terminar una implementación
funcional, iniciar o reiniciar la aplicación, indicar la URL y esperar la
validación; las tareas exclusivamente documentales no requieren reinicio.
Estas reglas se aplican también a PB-002-FIX-003. Trabajar en `develop`, sin
ramas, commits ni push; mantener **TOOLS FIRST, AI SECOND**.

## Registro PB-002-FIX-001 — 2026-11-24

### Documentación revisada y creada

- Revisados íntegramente `.github/copilot-instructions.md`,
  `copilot-instructions-python.md`, `README.md`, `docs/ARCHITECTURE.md`,
  `docs/PROGRESS.md` y los ADR 0001/0002.
- `docs/ROADMAP.md` no existía; se creó con el checklist de fases 0–8 y
  estados de implementación, pruebas automáticas, validación manual y bloqueo.
- Se añadieron reglas permanentes para consultar/actualizar el roadmap y el
  progreso en cada ejecución, preservar historial y distinguir mocks de
  validaciones reales. Se registró la estrategia **TOOLS FIRST, AI SECOND**,
  sin implementar IA.

### Incidencia y solución

- Incidencia: el servicio rechazaba todas las URLs QuickConnect antes de
  solicitar la API; el fragmento HTMX incluía el mismo error tanto en el
  resultado como en la lista de sesiones.
- El cliente resuelve el alias corto sin credenciales y solo acepta
  redirecciones HTTPS dentro de `quickconnect.to`, `quickconnect.cn` y sus
  subdominios. Rechaza destinos externos, rutas inválidas y HTTP; descarta las
  cookies de resolución y no sigue redirecciones en las llamadas API/login.
- Se consulta `SYNO.API.Info` y se exige la disponibilidad de Auth, List y
  Download antes de cargar credenciales de keyring o enviar las introducidas.
  Los destinos que devuelven HTML/JSON incompatible reciben errores
  QuickConnect específicos.
- Las conexiones por IP, DDNS y VPN directa siguen disponibles. La UI muestra
  explícitamente que resolver el endpoint/API no equivale a validación real.
- Se solucionó la duplicación del error limitando su contexto en el fragmento
  de la lista de sesiones.

### Archivos modificados o creados

- Instrucciones: `.github/copilot-instructions.md`,
  `copilot-instructions-python.md`.
- Seguimiento/documentación: `README.md`, `docs/ROADMAP.md`,
  `docs/ARCHITECTURE.md`, este registro y
  `docs/adr/0003-quickconnect-resolution.md`.
- Implementación/UI: `app/application/services/synology_connections.py`,
  `app/infrastructure/synology/client.py`,
  `app/presentation/templates/connections.html` y
  `app/presentation/templates/connection_result.html`.
- Pruebas: `tests/helpers/synology.py`,
  `tests/unit/test_synology_connections.py` y
  `tests/integration/test_synology_ui.py`.

### Pruebas ejecutadas

- Estado previo registrado para fase 1: 46 aprobadas, 1 omitida; mocks HTTP.
- `.\.venv\Scripts\python.exe -m pytest -q` — **58 aprobadas, 1 omitida**.
  Incluye resolución regional, URL regional directa, redirección permitida,
  destino no autorizado, downgrade HTTP, API/HTML/JSON, error de conexión,
  protección ante reenvío de credenciales, conexiones directas y un solo
  mensaje de error UI. No hubo conexiones a NAS.
- `.\.venv\Scripts\python.exe -m ruff check .` — correcto.
- `git diff --check` — correcto (avisos de Git sobre conversión LF/CRLF en
  instrucciones de Windows; sin errores de whitespace).
- Diagnósticos Pylance de workspace — ninguno.
- Pylance `checkSignatureCompatibility` para el constructor del cliente
  Synology — los 8 call sites son compatibles.
- Arranque actualizado en `127.0.0.1:8001`: `/`, `/health` y `/connections`
  respondieron HTTP 200; la página de conexiones presenta el formato de alias
  QuickConnect y explica la comprobación de API. El puerto por defecto 8000 ya
  estaba ocupado, no se detuvo ni modificó ese proceso.

### Estado y limitaciones

- Fase 1 sigue implementada y testada automáticamente, pero no validada
  manualmente en hardware real.
- **QuickConnect no está garantizado ni marcado como validado.** Los tests
  simulan una redirección HTTPS de alias a dominio regional y el descubrimiento
  de API; no prueban DNS, certificados, relay, autenticación ni permisos del
  NAS del usuario.
- Una redirección a un host fuera de los dominios QuickConnect se rechaza; en
  ese caso se debe usar una URL DSM/DDNS o VPN directa de confianza.
- Continúan las limitaciones de fase 1: sesiones/operaciones en memoria, no
  hay recuperación tras reinicio y una prueba de enlace simbólico queda
  omitida cuando Windows no permite crear el enlace.
- Sin Amazon Photos, IA, LLM, Copilot SDK ni skills; no se inicia fase 2.

### Repetir la prueba

1. La instancia actual está disponible en `http://localhost:8001` porque el
   puerto 8000 estaba ocupado. Si la detienes, arranca la aplicación con el
   comando alternativo de README; normalmente puede usarse
   `.\scripts\start.ps1` en el puerto 8000 libre.
2. Abre **Conexiones**.
3. Introduce `https://quickconnect.to/<ID>` con el QuickConnect ID real,
   usuario y contraseña; pulsa **Probar conexión**.
4. Comprueba el endpoint regional, autenticación y permisos de lectura. Si se
   solicita MFA, introduce el código manualmente.
5. En **Explorador**, probar Synology Photos si aparece como disponible;
   verificar espacio personal/compartido, carpetas, álbumes y miniaturas.
6. Descargar manualmente una sola fotografía y comprobar que el archivo se
   abre, su tamaño y el informe JSON. No desactivar la verificación TLS.

## Registro PB-002-FIX-002 — 2026-11-24

### Investigación

- Se confirmó que Synology no publica una guía oficial de API web para
  Synology Photos. `SYNO.Foto.*` y `SYNO.FotoTeam.*` son interfaces internas
  del paquete; los contratos se corroboraron con manifiestos/referencias
  comunitarias: `zeichensatz/SynologyPhotosAPI`, `N4S4/synology-api` y
  `pmilano1/synology-dsm-api`.
- `SYNO.API.Info` permite descubrir dinámicamente los nombres, versiones y
  rutas en `/photo/webapi/query.cgi`. Se investigaron Browse Item/Folder/Album,
  FotoTeam Browse Item/Folder, Thumbnail y Download. No se implementó una API
  `SYNO.FotoTeam.Browse.Album` no corroborada.
- La evidencia manual previa del usuario para QuickConnect, autenticación DSM,
  APIs y permisos File Station se registra como validación manual de conexión
  (3515 ms). No hubo conexión real ni validación manual de Synology Photos
  durante esta tarea.

### Implementación

- Añadidos modelos tipados Photos y un adaptador separado que comparte HTTPX,
  TLS y sesión DSM, y usa `X-Syno-Token`/cookie `id` solo en peticiones
  servidor-a-servidor.
- Diagnóstico ampliado con disponibilidad anunciada de APIs, acceso probado a
  espacios personal/compartido y consulta de álbumes personales.
- El explorador prefiere la biblioteca Photos cuando está disponible, incluye
  navegación por espacios/carpetas, álbumes personales, cuadrícula con carga
  diferida de miniaturas, filtros en la página, fecha de captura cuando existe,
  selección y descarga manual mediante el servicio común.
- File Station sigue disponible sin cambios funcionales. Los IDs Photos no se
  convierten en rutas físicas; el staging utiliza
  `SynologyPhotos/<espacio>/<id_carpeta>/<nombre>`.
- Añadidos límites/validaciones de ruta para nombres Photos y datos de origen
  en los informes JSON. No se añadieron dependencias ni se inició otra fase.

### Archivos creados o modificados

- `app/domain/models/photos.py`, `app/domain/models/synology.py`.
- `app/infrastructure/synology/client.py`,
  `app/infrastructure/synology/photos.py`.
- `app/application/services/synology_connections.py`,
  `app/application/services/synology_downloads.py`.
- `app/presentation/api/synology_routes.py`,
  `app/presentation/templates/explorer.html`,
  `app/presentation/templates/connection_result.html`,
  `app/presentation/static/styles.css`.
- `tests/helpers/synology.py`,
  `tests/unit/test_synology_photos.py`,
  `tests/integration/test_synology_ui.py`.
- `README.md`, `docs/ARCHITECTURE.md`, este registro,
  `docs/ROADMAP.md`, `.github/copilot-instructions.md` y
  `docs/adr/0004-synology-photos-adapter.md`.

### Pruebas y estado

- `.\.venv\Scripts\python.exe -m pytest -q` — **69 aprobadas, 1 omitida**.
  Los tests usan mocks; no conectan al NAS. La omitida depende de poder crear
  enlaces simbólicos en Windows.
- `.\.venv\Scripts\python.exe -m ruff check .` — correcto.
- Diagnóstico Pylance del workspace — **0 diagnósticos**.
- `git diff --check` — correcto; Git avisó de conversión LF/CRLF en
  instrucciones de Windows.
- Tests nuevos cubren descubrimiento, capacidades, permisos, paginación,
  espacios, álbumes, filtros, miniaturas proxied, descarga original en
  streaming, hash local, límites, informe y continuidad de File Station.

### Limitaciones y validación pendiente

- Las APIs Photos son internas, pueden cambiar entre versiones DSM y no tienen
  garantía de compatibilidad. Un mock satisfactorio no valida el NAS real.
- Los filtros de nombre/extensión/fecha se aplican a la página solicitada y no
  hacen búsqueda global. Fecha de captura no se sustituye por fecha de
  modificación.
- Algunas variantes FotoTeam de miniaturas/descargas no se pudieron validar
  por ausencia de conexión real. Tampoco se verificó la sesión, la apertura de
  originales ni el comportamiento de HEIC en el NAS del usuario.
- QuickConnect/File Station tiene validación manual comunicada por el usuario;
  la descarga real File Station continúa pendiente. Synology Photos sigue
  pendiente de validación manual. No se comenzó fase 2 ni IA.

### Pasos manuales para Synology Photos

1. Arrancar PhotoBridge en `127.0.0.1`; abrir **Conexiones** e iniciar
   manualmente la conexión HTTPS.
2. Revisar el diagnóstico de APIs, espacios personal/compartido y álbumes.
   Si Photos no se anuncia o el acceso da error, mantener File Station como
   alternativa.
3. En **Explorador**, navegar a una carpeta y comprobar fechas, extensiones y
   miniaturas; los filtros consultan solo la página mostrada.
4. Seleccionar una única foto, confirmar la descarga y verificar el archivo en
   `data/downloads/<id_conexion>/SynologyPhotos/` y el informe en
   `.reports/`. Confirmar manualmente si abre y si su tamaño coincide con el
   indicado por Photos.
5. Informar el resultado real antes de marcar Synology Photos como validado.

## Registro PB-DOC-004 — 2026-11-24

- Actualizadas las instrucciones permanentes de Copilot con el nuevo flujo:
  implementar solo lo solicitado, no crear ni ejecutar pruebas/comprobaciones,
  no conectar a servicios externos en pruebas y dejar la validación funcional
  al usuario.
- Se exige mantener separadas las funcionalidades implementadas y las
  pendientes de validación manual, actualizar Roadmap y Progress, e iniciar la
  aplicación al concluir implementaciones funcionales. Se excluyó el reinicio
  para tareas solo documentales.
- Se indicó expresamente que la metodología aplica a `PB-002-FIX-003`, que el
  trabajo permanece en `develop` y que no se crean ramas, commits ni push.
- En esta tarea documental no se implementó funcionalidad de la aplicación ni
  se ejecutaron pruebas, linters, comprobaciones de tipos, pruebas HTTP,
  conexiones externas ni comprobaciones automatizadas. Se conservaron las
  pruebas existentes. Los resultados **69 aprobadas, 1 omitida** registrados
  para PB-002-FIX-002 son antecedentes, no pruebas ejecutadas en esta tarea.
- Synology Photos sigue implementado, pero pendiente de validación funcional
  manual confirmada por el usuario; la evidencia previa de QuickConnect y
  File Station no se amplía a Photos.

## Registro PB-TOOLS-001 — 2026-11-24

- Configuración MCP de usuario de VS Code: `%APPDATA%\Code\User\mcp.json`.
  Se mantienen los servidores existentes y se agregan `chrome-devtools` y
  `playwright`.
- Chrome DevTools MCP se destina prioritariamente a inspección de APIs,
  peticiones/respuestas HTTP, payloads, endpoints y consola. Microsoft
  Playwright MCP se destina a navegación e interacción, incluido acceso a
  aplicaciones autenticadas.
- Cada servidor usa un perfil local persistente y separado bajo
  `%LOCALAPPDATA%\Copilot\MCPProfiles\`; el usuario inicia sesión y completa
  MFA manualmente. No se almacenan credenciales en `mcp.json`.
- Requisitos encontrados: Node.js, npm, npx y Chrome están disponibles. Los
  paquetes MCP se obtendrán mediante `npx` al iniciar los servidores.
- Estas herramientas son de desarrollo de Copilot, no dependencias de
  PhotoBridge. La investigación MCP solo se realiza cuando se solicita; no
  mostrar secretos ni modificar datos externos sin autorización.
- No se modificó código de la aplicación, no se inició PB-002-FIX-003 y no se
  ejecutaron pruebas ni comprobaciones. El usuario sigue siendo responsable de
  las pruebas funcionales de PhotoBridge.

## Registro PB-002-FIX-003 — 2026-11-24

- **Implementado:** Synology Photos consulta `SYNO.API.Info` en el endpoint DSM
  observado `/webapi/entry.cgi` y usa el listado `SimilarItem.list` observado
  mediante POST para la biblioteca general. Se conserva `Browse.Item` para
  vistas por carpeta/álbum y File Station permanece separado.
- **Implementado:** diagnóstico de acceso personal/compartido por lecturas
  limitadas; la vista web incluye fotos y vídeos, filtros básicos, páginas de
  hasta 50, fecha reportada por Photos, tamaño, tipo y resolución cuando existe.
  Las miniaturas se solicitan por backend y sus fallos individuales muestran
  un icono alternativo.
- **Restringido deliberadamente:** no se investigó el contrato de descarga
  original de Photos ni se inició descarga. El diagnóstico no la declara
  disponible, la selección queda bloqueada y File Station conserva su flujo
  existente. Los vídeos no se pueden seleccionar como descargas.
- **Documentación:** añadido `docs/SYNOLOGY-PHOTOS-API.md` con endpoints,
  parámetros observados, sesión, capacidades y límites; actualizado el ADR
  0004, ROADMAP y este registro.
- **Evidencia de investigación:** el sitio DSM real confirmó respuestas de
  lectura con fotos y vídeos, álbumes y miniaturas, tras autenticación manual
  del usuario. `SYNO.Foto.*`/`SYNO.FotoTeam.*` siguen siendo APIs internas; esta
  evidencia no constituye validación de PhotoBridge.
- **Validación pendiente:** el usuario debe confirmar en PhotoBridge la
  conexión QuickConnect, la biblioteca, filtros, carpetas/álbumes, miniaturas y
  la vista de ambos tipos de medio. No se marca ninguna capacidad de la
  aplicación como validada manualmente.
- **Metodología:** no se crearon ni ejecutaron tests, pytest, Ruff, Pylance,
  linters, comprobaciones de tipos, pruebas HTTP ni pruebas funcionales de
  PhotoBridge. No se realizaron descargas ni acciones destructivas. Los
  resultados históricos de PB-002-FIX-002 no se repitieron.
- **Archivos modificados:** `app/infrastructure/synology/client.py`,
  `app/infrastructure/synology/photos.py`,
  `app/domain/models/photos.py`,
  `app/application/services/synology_connections.py`,
  `app/application/services/synology_downloads.py`,
  `app/presentation/api/synology_routes.py`,
  `app/presentation/templates/explorer.html`,
  `app/presentation/static/photobridge.js`,
  `docs/SYNOLOGY-PHOTOS-API.md`,
  `docs/ROADMAP.md`, `docs/PROGRESS.md` y
  `docs/adr/0004-synology-photos-adapter.md`.
- **Arranque:** PhotoBridge se inició en `127.0.0.1:8002` para validación
  manual. No se realizaron comprobaciones de salud ni solicitudes HTTP.

## Registro PB-002-FIX-004 — 2026-11-24

- **Incidencia manual comunicada:** `POST /api/synology/connect` devolvió
  HTTP 500 por un `TypeError`: la llamada desde `stream_thumbnail` pasaba
  `require_image`, que `open_photo_thumbnail_stream` no admite.
- **Implementado:** eliminado exclusivamente ese argumento de la llamada.
  El método especializado ya impone `require_image=True` al abrir el stream:
  se conserva el rechazo de respuestas cuyo Content-Type no es `image/*`.
  Se consultaron la firma y sus puntos de invocación afectados.
- **Capacidades independientes:** el diagnóstico mantiene autenticación,
  acceso a biblioteca y álbumes disponibles aunque falle una miniatura.
  Respuestas de miniatura vacías se notifican explícitamente; los errores
  de álbumes y miniaturas se añaden al mensaje sin ocultarse. Solo se capturan
  errores específicos `SynologyClientError`, no errores de programación.
- **Alcance:** modificados `app/infrastructure/synology/photos.py`,
  `app/application/services/synology_connections.py`, este documento y ROADMAP.
  No se modificó el adaptador File Station ni se eliminaron archivos.
- **Validación pendiente:** el usuario debe repetir la conexión y confirmar
  el resultado. No se crearon ni ejecutaron tests, validadores, pruebas HTTP,
  MCP ni conexiones al NAS; no se marca la funcionalidad como validada.
- **Reinicio:** PhotoBridge reiniciado en `http://127.0.0.1:8002`.
  Uvicorn informó arranque completo; no se realizaron solicitudes HTTP.

## Precarga local del formulario Synology — 2026-11-24

- **Implementado:** campos editables de nombre, URL HTTPS y usuario DSM
  precargados mediante configuración local. La URL se confirmó con el usuario.
  Los valores particulares quedan en `.env`, excluido de Git, no en el código
  ni en la documentación compartida. La contraseña permanece vacía; el inicio
  de conexión y cualquier MFA siguen siendo manuales.
- **Archivos:** `app/config.py`, `app/presentation/api/synology_routes.py`,
  `app/presentation/templates/connections.html`, `.env` local, `.env.example`,
  README, ROADMAP y este registro.
- **Validación pendiente:** el usuario debe confirmar los campos del formulario.
  No se crearon ni ejecutaron pruebas, validadores o conexiones al NAS.
- **Reinicio:** Uvicorn informó arranque completo en `127.0.0.1:8002`;
  no se realizaron pruebas HTTP.

## Registro PB-002-FIX-005 — 2026-11-24

- **Validado manualmente por el usuario:** conexión con Synology Photos,
  visualización de fotografías reales, miniaturas y apertura de imagen XL.
  No se extiende esta confirmación a álbumes, vídeos, permisos compartidos,
  filtros ni descarga de originales.
- **Investigación de lectura mediante Chrome DevTools MCP:** consultados
  `SYNO.Foto.Browse.Album.list`, `Browse.Album.get` (ID en array JSON) y
  `Browse.Item.list` por `album_id`. El álbum controlado devolvió un elemento
  de tipo fotografía. Se verificó la serialización JSON de cadenas/listas en
  los parámetros de lectura; no se usan nombres como identificadores.
- **Contrato de originales:** inspeccionado el código servido por la interfaz
  oficial. Esta construye POST `SYNO.Foto.Download.download` con `item_id`
  como array JSON, `album_id`, `force_download=true`, `download_type=source`.
  No es la miniatura XL. La descarga múltiple y la descarga de álbum completo
  pueden producir ZIP; PhotoBridge solicita solo un original por llamada.
  No se verificó una respuesta binaria original ni se realizaron descargas
  desde PhotoBridge. No se presenta la investigación como validación funcional.
- **Implementado:** búsqueda de nombres en hasta 1000 álbumes paginados, aviso
  explícito si se alcanza ese límite y navegación de álbumes por páginas de
  50. Selector por ID, cantidad reportada, contenido paginado, miniaturas,
  checkbox individual, seleccionar fotografías visibles y limpiar selección.
  Al cambiar de álbum se limpia la selección anterior.
- **Implementado:** previsualización de la operación con álbum, nombres,
  cantidad, tamaño estimado y destino; segundo formulario con confirmación
  explícita. Backend restringido a fotografías conocidas del álbum activo,
  máximo 10/250 MB y una operación secuencial, con protección CSRF.
- **Destino configurable:** `data/downloads/<nombre_album>/<nombre_archivo>`.
  Se sanea cada componente Windows, se bloquean traversal y enlaces, no se
  sobrescriben destinos y se informa de los archivos omitidos.
  Álbumes con nombres iguales o nombres que saneen al mismo destino pueden
  compartir carpeta; las colisiones de archivos se omiten, nunca se reemplazan.
- **Política no destructiva:** no se elimina ningún parcial, tampoco ante
  cancelación o tamaño incorrecto. Al completar se publica un enlace local sin
  sobrescritura y se conserva `.part`; puede representar los mismos bytes por
  enlace duro. Informes JSON creados sin reemplazar ni borrar su temporal.
  Esta conservación también se aplica al servicio compartido de File Station.
- **Estado visible:** esperado/descargado, progreso, estado por archivo,
  destino, parcial y motivo de error. SHA-256 local, sin afirmar igualdad
  criptográfica con el NAS. No se implementan vídeos ni otros proveedores.
- **Documentación:** actualizados ROADMAP, este registro, API Photos,
  arquitectura y ADR 0004; README refleja el nuevo flujo.
- **Pendiente de validación manual:** el usuario realizará la primera descarga
  desde PhotoBridge y confirmará archivo original, tamaño, nombre, ruta y
  conservación de parciales. No se crearon ni ejecutaron tests, Ruff, Pylance,
  linters, comprobaciones automatizadas ni pruebas funcionales/HTTP de
  PhotoBridge. Sin ramas, commits, push ni acciones destructivas.
- **Arranque:** PhotoBridge iniciado en `http://127.0.0.1:8000`;
  Uvicorn informó arranque completo. No se hicieron solicitudes HTTP.

## Registro PB-002-CLOSE-001 — 2026-11-24

- **Validado manualmente por el usuario:** descarga individual de una
  fotografía desde PhotoBridge y presencia del archivo en su ordenador.
  La confirmación no acredita integridad binaria, igualdad con el original
  remoto, comparación de hashes, tamaño, EXIF ni otras capacidades.
- **Pendiente:** descargas múltiples y cualquier funcionalidad que el usuario
  no haya confirmado expresamente. Se mantienen las validaciones previas de
  conexión, fotografías, miniaturas y apertura XL, sin ampliar su alcance.
- **Entorno de validación:** el álbum `Test`, creado y gestionado manualmente
  por el usuario, queda registrado para futuras validaciones manuales de
  migración. No se afirma que esta descarga procediera de ese álbum, pues la
  confirmación recibida no lo especifica.
- **Fase 2 — Amazon Photos:** preparada documentalmente, no iniciada.
  Investigar viabilidad mediante mecanismos oficiales y desarrollar únicamente
  cuando el usuario lo autorice expresamente. No se da por validada toda la
  fase 1 ni se implementan migraciones en esta tarea.
- **NON-DESTRUCTIVE MIGRATION POLICY:** originales, álbumes, archivos y
  temporales permanecen intactos; sin eliminación, movimientos destructivos,
  sobrescrituras ni limpiezas automáticas.
- **Alcance documental:** actualizados únicamente ROADMAP y este registro.
  Sin cambios de código, eliminación de archivos, tests, comprobaciones,
  reinicio de aplicación, ramas, commits ni push. Se espera autorización
  para comenzar la fase 2.
