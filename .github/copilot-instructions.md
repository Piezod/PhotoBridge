# Photo Migration Manager — instrucciones para GitHub Copilot

## Objetivo
Aplicación local Windows para copiar fotos y vídeos originales desde cuentas remotas de Synology DSM/Photos a cuentas Amazon Photos independientes. Nunca borrar originales. Migración incremental, recuperable y auditable. Preparar portabilidad futura a Docker.

## Stack
Python 3.12, FastAPI, Uvicorn, HTTPX, Playwright Python, SQLAlchemy 2, SQLite, Alembic, Pydantic Settings, Jinja2, HTMX, Bootstrap 5, keyring, pytest, Ruff. Usar pyproject.toml y entorno virtual. No Angular, Java, Redis ni Celery. Monolito modular con arquitectura hexagonal pragmática.

## Estructura
- app/domain/models y ports: entidades, estados y contratos independientes del framework.
- app/application/services y use_cases: orquestación y reglas.
- app/infrastructure/synology, amazon, persistence, storage, security: adaptadores.
- app/presentation/api, templates, static: HTTP y vistas.
- app/config.py y main.py: configuración y composición.
- tests/unit, tests/integration; scripts; docs/adr; docs/PROGRESS.md.
- data/ para SQLite, temporales y perfiles de navegador; excluir de Git.

## Reglas de trabajo
Implementar exclusivamente la funcionalidad solicitada en cada prompt. Consultar solo el contexto y los documentos necesarios para esa tarea; no repetir análisis ni comprobaciones redundantes. Mantener tipado, funciones pequeñas, inyección de dependencias, errores explícitos y logs estructurados sin secretos. Usar async para HTTP y Playwright; no bloquear el event loop con operaciones de disco o hash. No añadir dependencias sin justificar.

### Metodología obligatoria de validación
- No crear pruebas unitarias ni de integración nuevas. Conservar las pruebas existentes sin ejecutarlas.
- No ejecutar pruebas existentes ni herramientas de validación automatizada: pytest, Ruff, Pylance, linters, comprobaciones de tipos, `git diff --check`, pruebas HTTP o comprobaciones funcionales automatizadas.
- No realizar conexiones de prueba a servicios externos. El usuario realiza las pruebas funcionales y comunica los errores para su corrección.
- No marcar ninguna funcionalidad como validada hasta recibir confirmación explícita del usuario. Mantener por separado lo implementado y lo pendiente de validación manual.
- Actualizar `docs/ROADMAP.md` y `docs/PROGRESS.md` en cada tarea pertinente, reflejando implementación y validación pendiente; conservar el historial y no inventar resultados.
- Al terminar una implementación funcional, arrancar o reiniciar PhotoBridge en `127.0.0.1`, indicar la URL accesible y resumir brevemente los cambios; detenerse y esperar la validación del usuario. No reiniciar por una tarea exclusivamente documental.
- Aplicar estas restricciones también a `PB-002-FIX-003`, además de cualquier prompt posterior.
- Trabajar únicamente en `develop`: no crear ramas, commits ni hacer push.
- Minimizar el consumo de tokens, evitar refactorizaciones no solicitadas y no realizar comprobaciones adicionales tras implementar los cambios.

Estas reglas prevalecen sobre cualquier instrucción previa que exija crear o ejecutar pruebas o comprobaciones automatizadas. Mantener **TOOLS FIRST, AI SECOND**; no implementar IA, LLM ni skills sin autorización expresa.

### MCP de navegador para investigación solicitada
- Usar Chrome DevTools MCP preferentemente para investigar APIs, tráfico de red, peticiones/respuestas HTTP, payloads, errores de consola y endpoints.
- Usar Microsoft Playwright MCP para navegar e interactuar con páginas, pestañas, DOM y aplicaciones autenticadas. Priorizar la investigación autónoma mediante estas herramientas frente a pedir capturas manuales.
- La investigación técnica mediante MCP está permitida cuando el usuario la solicite; esto no modifica la metodología de pruebas de PhotoBridge: el usuario sigue siendo responsable de su validación funcional.
- Mantener perfiles dedicados y persistentes; el usuario introduce credenciales y completa MFA manualmente. No guardar credenciales en código/configuración ni mostrar o registrar cookies, contraseñas, tokens o identificadores de sesión.
- No realizar acciones destructivas en sitios externos. Solicitar autorización expresa antes de modificar datos externos.
- Estos servidores MCP son herramientas de desarrollo de Copilot y no dependencias ni componentes de la aplicación Python.

## Seguimiento documental obligatorio
En cada ejecución, consultar estas instrucciones y las secciones/documentos pertinentes a la tarea, sin lecturas redundantes. Consultar y actualizar `docs/ROADMAP.md` y `docs/PROGRESS.md`; si alguno no existe, crearlo sin inventar historial. Mantener el progreso previo y añadir un registro fechado/identificado por tarea; actualizar también el estado vigente del roadmap. No ejecutar las validaciones automatizadas que se enumeran en la sección anterior.

El roadmap debe agrupar criterios por fases y distinguir explícitamente `Pendiente`, `Implementado`, `Testado automáticamente`, `Validado manualmente` y `Bloqueado`. Solo marcar validación manual cuando exista confirmación expresa del usuario; los resultados históricos de pruebas no equivalen a validación funcional real. No ejecutar pruebas para actualizar el estado: registrar únicamente resultados históricos ya comunicados y anotar que la validación nueva queda a cargo del usuario.

## Evolución de arquitectura
Mantener los servicios de conexión, exploración, descarga y subida independientes de la interfaz y utilizables mediante contratos de aplicación. La estrategia futura es **TOOLS FIRST, AI SECOND**: las herramientas y reglas de negocio deben ser correctas, seguras y verificables antes de integrarlas con Copilot SDK o skills. No implementar IA, LLM ni skills sin autorización expresa para su fase.

## Synology Photos
Mantener Synology Photos y File Station como adaptadores separados; preferir Photos para la biblioteca indexada solo cuando `SYNO.API.Info` y las comprobaciones de lectura respalden la capacidad. Descubrir las rutas/versiones dinámicamente; no fijar versiones DSM ni asumir que Photo IDs son rutas File Station.

Las API web `SYNO.Foto.*` y `SYNO.FotoTeam.*` son interfaces internas/no documentadas por Synology. Antes de usarlas, comprobar fuentes y contratos observables, diferenciar documentación oficial de ingeniería inversa y documentar las incertidumbres en ADR/PROGRESS. No presentar disponibilidad descubierta como compatibilidad garantizada ni marcar una integración manual como validada sin confirmación real del usuario. Mantener cookies, SID y tokens en el backend; no exponerlos en navegador, URLs visibles, logs o informes. Las pruebas deben usar mocks y nunca conectar a un NAS automáticamente.

## Seguridad
Escuchar solo en 127.0.0.1 por defecto. Validar origen de solicitudes y proteger operaciones mutables contra CSRF. Credenciales Synology mediante keyring de Windows; nunca en SQLite, .env, Git o logs. En otros sistemas exigir almacén seguro compatible o entrada manual. Amazon: inicio manual en navegador visible y perfil persistente separado por cuenta, protegido mediante permisos locales. No almacenar contraseñas Amazon ni automatizar CAPTCHA/MFA. No desactivar TLS; aceptar CA de confianza configurada cuando proceda. Validar URL y limitar redirecciones para no reenviar secretos a terceros. Redactar tokens y cookies. Evitar traversal de rutas y nombres peligrosos. No exponer la aplicación a Internet. Usar cuentas con permisos mínimos de lectura en Synology.

## Contratos y modelo
SourceProvider: connect, list_files (paginado), stat, download (streaming). DestinationProvider: authenticate, upload, verify; devolver evidencia y distinguir resultado incierto. CredentialStore y repositorios como puertos. Entidades: SourceAccount, DestinationAccount, MigrationJob, MediaItem, TransferAttempt. Cada trabajo asocia exactamente un origen y un destino. Guardar ruta remota, tamaño, fecha, SHA-256 cuando se descarga, destino, intentos, estado y evidencia de verificación. Identidad de origen por cuenta+ruta+versión (tamaño/fecha como indicios, no prueba criptográfica). Duplicados por hash y destino, nunca entre cuentas diferentes. No afirmar que un archivo preexistente en Amazon coincide solo por nombre.

## Proceso de transferencia
Descubrir -> encolar -> descargar a .part -> validar tamaño y calcular hash -> renombrar atómicamente -> subir -> verificar -> registrar confirmación -> limpiar copia temporal. Estados: DISCOVERED, QUEUED, DOWNLOADING, DOWNLOADED, UPLOADING, VERIFYING, VERIFIED, RETRYABLE_ERROR, PERMANENT_ERROR, UNCERTAIN, PAUSED. Persistir transiciones; tras caída reconciliar estados intermedios. No reintentar ciegamente una subida incierta. Si no se puede verificar, conservar temporal y solicitar revisión. Diferenciar confirmación visual de verificación criptográfica; no prometer esta última si Amazon no la permite. Nunca borrar archivos remotos. Límite de disco configurable (inicial 2 GiB), contemplar archivos mayores y espacio libre; contrapresión y concurrencia inicial 1. Reintentos acotados con backoff y jitter para fallos transitorios. Preservar bytes originales y EXIF; álbumes virtuales, etiquetas y reconocimiento facial fuera del MVP. Vídeos sujetos a cuota del destino.

## Fases y criterios de aceptación
### 0 — Bootstrap
Crear estructura, pyproject, configuración, .gitignore, README, PROGRESS, app FastAPI con GET /health y página inicial, pytest y Ruff. Sin integraciones reales. Aceptación: arranque local y tests verdes.
### 1 — Synology remoto
Descubrir APIs mediante SYNO.API.Info; autenticar con SYNO.API.Auth; listar y descargar con File Station según versiones y rutas descubiertas. No asumir que QuickConnect permite acceso directo a API: probar URL real DSM/DDNS/VPN, manejar redirecciones y MFA manual si procede. Explorar /home/Photos y /photo según permisos. Cerrar sesión cuando proceda. Pruebas HTTP simuladas y script manual para listar y descargar un archivo. Aceptación: original descargado y tamaño comprobado; sin cambios remotos.
### 2 — Amazon Photos: puerta de viabilidad
No hay API pública general de subida asumida. Probar navegador visible con perfil persistente, login manual y subida mediante interfaz oficial, respetando condiciones del servicio y límites. No usar endpoints privados ni eludir controles. Probar 10 archivos propios de ejemplo, incluidos nombres repetidos y formatos admitidos. Documentar evidencia observable de subida, errores, duplicados y sesión caducada. Si no es fiable o permitido, detener automatización y evaluar aplicación oficial de escritorio con carpeta de staging y confirmación manual. No implementar fases posteriores hasta decidir viabilidad.
### 3 — Inventario
Escaneo recursivo paginado, filtros de extensiones configurables, exclusión de miniaturas y carpetas internas, persistencia e informe de volumen. No descargar todo para inventariar. Aceptación: escaneo repetido sin duplicar registros, tests de paginación y permisos.
### 4 — Motor de migración
Implementar contratos, cola persistente, máquina de estados, staging limitado, hash, subida y verificación. Primero adaptadores falsos; luego integrar proveedores validados. Aceptación: transferencia de prueba, originales intactos y limpieza solo tras confirmación.
### 5 — Recuperación
Pausa, cancelación segura, reinicio, reintentos, reconciliación y reporte de incertidumbres. SQLite WAL y transacciones breves. Un worker por defecto, evitar duplicar workers con recarga de desarrollo. Aceptación: simular caída en cada etapa y demostrar recuperación sin reenvío ciego.
### 6 — Interfaz web
Pantallas de cuentas, prueba de conexión, selector de carpetas, inventario, creación de trabajo, progreso, errores y revisión manual. HTMX para actualización periódica. No mostrar secretos. Aceptación: flujo completo desde localhost.
### 7 — Multicuenta
Perfiles y sesiones aislados, asociación explícita origen/destino, confirmación de identidad antes de subir. Aceptación: pruebas de aislamiento y ausencia de cruces de datos.
### 8 — Incremental y despliegue
Escaneo incremental, ejecución manual y programación opcional, sin propagar borrados. Documentar Windows, copias de SQLite, recuperación y posteriormente Docker. Aceptación: segunda ejecución solo procesa archivos nuevos o modificados según reglas de identidad.

## Comandos previstos
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .

## Definición de terminado
Código, pruebas, documentación, criterios de aceptación verificados y PROGRESS.md actualizado. Las pruebas con servicios reales requieren autorización y credenciales introducidas localmente. No confundir simulación con integración real.
