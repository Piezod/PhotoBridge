# Roadmap de PhotoBridge

Este documento conserva el alcance y el estado verificable de las fases
definidas por el proyecto. El estado manual solo cambia cuando una persona
confirma la prueba con el servicio real; las pruebas simuladas no cuentan como
validación de integración.

## Estados

- **Pendiente**: no implementado o sin ejecutar.
- **Implementado**: existe código/documentación para el criterio.
- **Testado automáticamente**: cubierto por una ejecución reproducible de
  pruebas o comprobaciones locales.
- **Validado manualmente**: confirmado expresamente por el usuario con el
  servicio/dispositivo real.
- **Bloqueado**: no continuar hasta cumplir una dependencia/decisión indicada.

## Metodología de desarrollo vigente

- Implementar solo lo solicitado. No crear pruebas ni ejecutar pruebas
  existentes; conservarlas sin ejecución.
- No ejecutar pytest, Ruff, Pylance, linters, comprobaciones de tipos,
  `git diff --check`, pruebas HTTP ni comprobaciones funcionales automatizadas.
  No realizar conexiones de prueba a servicios externos.
- El usuario es responsable de las pruebas funcionales. No marcar una
  funcionalidad como validada sin confirmación explícita del usuario.
- Actualizar este roadmap y `docs/PROGRESS.md` con lo implementado y lo
  pendiente de validación, conservando el historial y sin inventar resultados.
- Al completar una implementación funcional, iniciar o reiniciar la aplicación,
  indicar su URL y esperar las pruebas del usuario. No reiniciar en tareas solo
  documentales.
- Aplicar estas reglas también a `PB-002-FIX-003`. Mantenerse en `develop`:
  no crear ramas, commits ni hacer push. Mantener **TOOLS FIRST, AI SECOND**.
- Herramientas de desarrollo MCP de navegador: Chrome DevTools MCP para
  inspección de APIs/tráfico HTTP y Microsoft Playwright MCP para navegación e
  interacción, únicamente en investigaciones solicitadas. No son dependencias
  de PhotoBridge; no exponen secretos ni modifican datos externos sin permiso.

## Fase 0 — Bootstrap

- [x] [Implementado] Estructura modular, configuración Python 3.12 y proyecto
  instalable.
- [x] [Implementado] FastAPI/Uvicorn, `GET /health`, página de inicio y
  Bootstrap/HTMX local; bind solo a `127.0.0.1`.
- [x] [Implementado] Modo de prueba, máximo de 10 fotografías, prohibición de
  borrar originales, confirmación manual y migraciones automáticas desactivadas.
- [x] [Implementado] `.gitignore`, `.env.example`, README, scripts de Windows,
  pytest y Ruff.
- [x] [Testado automáticamente] Tests de configuración/salud y smoke local
  HTTP 200 previamente documentado en `docs/PROGRESS.md`.
- [ ] [Validado manualmente] Instalación/arranque revisados por el usuario en
  su entorno Windows.

## Fase 1 — Conexión y descarga de Synology

- [x] [Implementado] Descubrimiento dinámico `SYNO.API.Info`, autenticación
  `SYNO.API.Auth`, sesión en servidor, MFA manual y cierre de sesión.
- [x] [Implementado] Conexiones HTTPS directas por IP, DDNS o VPN, CA de
  confianza opcional y credenciales recordadas con keyring.
- [x] [Implementado] Exploración autorizada paginada (máximo 50), filtro de
  fotografías, selección backend limitada a 10 y miniaturas si el NAS anuncia
  la API.
- [x] [Implementado] Descarga secuencial con confirmación, tope de 250 MB
  (250.000.000 bytes), streaming a `.part`, tamaño, hash local, cancelación,
  validación de rutas y colisiones, progreso e informe JSON.
- [x] [Implementado] QuickConnect: resolución inicial solo por HTTPS dentro
  de dominios QuickConnect permitidos; se comprueban `SYNO.API.Info` y las
  APIs Auth/List/Download antes de enviar credenciales.
- [x] [Testado automáticamente] Estado previo a PB-002-FIX-001: **46
  aprobadas y 1 omitida**, con mocks HTTP, sin NAS real.
- [x] [Testado automáticamente] PB-002-FIX-001: **58 aprobadas y 1 omitida**;
  mocks HTTP, sin conexión a NAS real. La omitida depende de poder crear
  enlaces simbólicos en Windows.
- [x] [Validado manualmente] El usuario confirmó resolución QuickConnect,
  conexión al NAS real, autenticación DSM, descubrimiento de APIs File Station,
  APIs de descarga/miniaturas y permisos de lectura. Latencia comunicada:
  **3515 ms**.
- [ ] [Validado manualmente] Confirmar una descarga original File Station,
  apertura del archivo y tamaño local en comparación con el remoto.
- [ ] [Bloqueado] No extrapolar la validación del usuario a otros dispositivos,
  relay/servicios QuickConnect o versiones DSM.
- [x] [Implementado] Adaptador Synology Photos separado de File Station;
  descubrimiento dinámico, espacios, carpetas, álbumes personales, miniaturas
  servidas por backend y descarga streaming con límites existentes.
- [x] [Implementado] PB-002-FIX-003: descubrimiento de lectura por
  `/webapi/entry.cgi`, listado de biblioteca con `SimilarItem.list`, paginación
  de 50, fotos/vídeos, filtros de tipo y presentación de resolución.
- [x] [Implementado] Diagnóstico de acceso personal/compartido por consultas de
  lectura; la miniatura solo se declara accesible tras recibir contenido de
  imagen. Vídeos no se pueden seleccionar para descarga.
- [x] [Implementado] PB-002-FIX-004: llamada de miniatura compatible con la
  firma del cliente, manteniendo su validación interna `require_image=True`.
  Fallos de miniaturas/álbumes se informan sin invalidar otras capacidades.
- [ ] [Validado manualmente] Repetir la conexión tras el HTTP 500 comunicado
  por el usuario en PB-002-FIX-003; corrección PB-002-FIX-004 pendiente de
  confirmación, sin pruebas automatizadas.
- [x] [Implementado] Precarga local configurable del nombre, URL HTTPS y
  usuario DSM del formulario; contraseña vacía y conexión manual.
- [ ] [Validado manualmente] Confirmar la precarga solicitada el 2026-11-24;
  no se ejecutaron comprobaciones automatizadas.
- [x] [Implementado] Documentación anonimizada de APIs observadas en
  `docs/SYNOLOGY-PHOTOS-API.md` y actualización del ADR 0004.
- [x] [Testado automáticamente] PB-002-FIX-002: **69 aprobadas, 1 omitida**;
  mocks HTTP, sin conexión real a NAS. Ruff correcto y Pylance sin diagnósticos.
- [ ] [Pendiente] La implementación de PB-002-FIX-003 no tiene comprobaciones
  automatizadas registradas; por metodología, no se crearon ni ejecutaron tests,
  linters o validaciones funcionales.
- [ ] [Validado manualmente] El usuario debe confirmar biblioteca, espacios,
  carpetas/álbumes, filtros y miniaturas desde PhotoBridge. La observación de
  tráfico DSM no valida la aplicación.
- [ ] [Bloqueado] `SYNO.Foto.*` y `SYNO.FotoTeam.*` son interfaces internas,
  sin compatibilidad garantizada. El contrato de descarga original no se
  investigó ni se inició ninguna descarga; no se declara habilitado.

## Fase 2 — Amazon Photos: puerta de viabilidad

- [ ] [Bloqueado] No iniciar hasta que el usuario valide la fase 1 y autorice
  expresamente esta fase.
- [ ] [Pendiente] Investigar viabilidad y condiciones mediante mecanismos
  oficiales; no asumir API pública general ni usar endpoints privados.
- [ ] [Pendiente] Evaluar navegador oficial visible con login manual y perfil
  por cuenta, sin guardar contraseñas ni automatizar MFA/CAPTCHA.
- [ ] [Pendiente] Probar, con autorización, 10 archivos propios y documentar
  evidencia observable, duplicados, errores y expiración de sesión.
- [ ] [Pendiente] Decidir si se continúa o se detiene en una carpeta staging y
  confirmación manual con la aplicación oficial.

## Fase 3 — Inventario

- [ ] [Pendiente] Escaneo recursivo paginado, configurable y limitado a las
  ubicaciones/permisos autorizados.
- [ ] [Pendiente] Filtros de extensión y exclusión de miniaturas/carpetas
  internas; persistir ruta, tamaño, fechas e indicios de versión.
- [ ] [Pendiente] Repetición idempotente sin duplicar registros y reporte de
  volumen, probado con mocks.
- [ ] [Bloqueado] No implementar hasta decidir viabilidad de fase 2 y recibir
  autorización expresa.

## Fase 4 — Motor de migración

- [ ] [Pendiente] Puertos SourceProvider/DestinationProvider y flujo de estados
  con staging, hash y verificación.
- [ ] [Pendiente] Adaptadores falsos primero; nunca inferir igualdad remota
  solo por nombre ni borrar originales.
- [ ] [Bloqueado] Espera validación de fase 2 y autorización específica.

## Fase 5 — Recuperación

- [ ] [Pendiente] Persistencia de trabajos, reconciliación, pausa/cancelación
  segura, reintentos limitados y estados inciertos.
- [ ] [Pendiente] SQLite WAL/transacciones breves y pruebas de caída en cada
  etapa; no reenvío ciego de subidas inciertas.
- [ ] [Bloqueado] Espera autorización de la fase correspondiente.

## Fase 6 — Interfaz web

- [x] [Implementado] Interfaz actual en español para conexión Synology,
  exploración y descarga manual; HTMX/Bootstrap local y endpoints POST con CSRF.
- [x] [Testado automáticamente] Pruebas UI simuladas; páginas y acciones
  probadas sin NAS real.
- [ ] [Pendiente] Integrar pantallas restantes de trabajos, progreso,
  incertidumbres e historial cuando existan las fases base.
- [ ] [Validado manualmente] Flujo completo con usuario en `localhost`.
- [ ] [Bloqueado] No ampliar más allá de la UI de fase 1 sin autorización.

## Fase 7 — Multicuenta

- [ ] [Pendiente] Aislamiento de perfiles/sesiones y asociación explícita de
  origen/destino.
- [ ] [Pendiente] Confirmación de identidad antes de subir y pruebas de
  ausencia de cruces.
- [ ] [Bloqueado] Espera autorización específica.

## Fase 8 — Incremental y despliegue

- [ ] [Pendiente] Detección incremental manual/programada sin propagar
  borrados, configuración portable y recuperación documentada.
- [ ] [Pendiente] Documentar copias de SQLite y despliegue Windows; Docker solo
  cuando se autorice.
- [ ] [Bloqueado] Espera validación de fases anteriores y autorización.

## Arquitectura futura — Tools First, AI Second

- [x] [Implementado] Los servicios actuales de conexión, exploración y
  descargas residen en la capa de aplicación, separados de las rutas y
  plantillas.
- [ ] [Pendiente] Mantener contratos tipados y resultados verificables para
  futura exposición como herramientas.
- [ ] [Bloqueado] Copilot SDK, skills, LLM e IA quedan fuera de alcance hasta
  autorización expresa; primero completar y validar las herramientas
  deterministas.

## Historial de estado

- 2026-11-24 — Registro inicial del roadmap a partir de las instrucciones del
  proyecto, documentación disponible y fase 1 existente. El resultado previo
  registrado fue 46 aprobadas, 1 omitida; QuickConnect aún no se ha validado
  manualmente.
- 2026-11-24 — PB-002-FIX-001 eliminó el bloqueo incondicional, añadió
  resolución HTTPS QuickConnect restringida y pruebas automáticas. Resultado:
  58 aprobadas, 1 omitida. No se conectó a NAS; validación QuickConnect sigue
  pendiente del usuario.
- 2026-11-24 — Aplicación actual iniciada en `127.0.0.1:8001` para permitir la
  repetición manual; el puerto por defecto 8000 ya estaba ocupado y no se
  interrumpió ese proceso.
- 2026-11-24 — El usuario confirmó conexión QuickConnect real, autenticación
  DSM, APIs File Station y permisos de lectura; 3515 ms. Queda pendiente la
  descarga real y no se extrapola a Synology Photos.
- 2026-11-24 — PB-002-FIX-002 implementó y testó con mocks el adaptador y UI de
  Synology Photos. Suite: 69 aprobadas, 1 omitida; sin NAS real. Validación
  manual Photos pendiente; API interna/no documentada. Fase 2 e IA no iniciadas.
- 2026-11-24 — PB-DOC-004 documentó la metodología de trabajo: sin crear ni
  ejecutar pruebas/comprobaciones, pruebas funcionales a cargo del usuario y
  ninguna validación manual sin confirmación explícita. Los resultados 69/1
  anteriores son históricos; no se ejecutó ninguna prueba en esta tarea.
- 2026-11-24 — PB-TOOLS-001 configuró a nivel de usuario Chrome DevTools MCP y
  Microsoft Playwright MCP con perfiles persistentes separados. Se conserva
  UnityMCP. Node.js/npm/npx y Chrome están instalados. Las herramientas son
  externas al runtime de PhotoBridge; login/MFA manuales y validación funcional
  de la aplicación a cargo del usuario.
- 2026-11-24 — PB-002-FIX-003 observó mediante DevTools las APIs DSM de
  biblioteca, álbumes y miniaturas en una sesión real de solo lectura. Se
  implementaron correcciones del conector y la vista de fotos/vídeos. No se
  iniciaron descargas originales ni se ejecutaron tests, validadores o pruebas
  de PhotoBridge; validación manual de la aplicación pendiente.
