# ADR 0004: Synology Photos como explorador preferente

- Estado: aceptada; validación manual de Synology Photos pendiente.
- Fecha: 2026-11-24.

## Contexto

File Station expone rutas físicas, pero no representa la biblioteca indexada de
Synology Photos y puede mostrar carpetas de respaldo que no corresponden a la
vista fotográfica que busca el usuario. La conexión DSM, TLS, QuickConnect y
la sesión de servidor ya existen y deben seguir sirviendo al adaptador File
Station sin regresiones.

Synology no publica una guía de desarrollador para las API web de Photos.
`SYNO.Foto.*` y `SYNO.FotoTeam.*` son interfaces internas del paquete; sus
parámetros se conocen principalmente mediante manifiestos del paquete y
referencias de ingeniería inversa de terceros. La estabilidad entre versiones
DSM no está garantizada.

## Decisión

- Añadir `SynologyPhotosClient` como adaptador separado, apoyado en el cliente
  HTTP y la sesión DSM existentes. File Station continúa disponible como vista
  complementaria.
- Consultar `SYNO.API.Info` en `/webapi/entry.cgi` y usar dinámicamente las
  rutas/versiones anunciadas. Si no se publican allí las APIs de biblioteca,
  comprobar únicamente las operaciones de lectura observadas y conocidas;
  no asumir acceso solo por una descripción de API.
- Usar `SYNO.Foto.Browse.SimilarItem.list` para el listado observado de la
  biblioteca general; `Browse.Item.list` para contenido de carpeta/álbum y
  `Browse.Album.list` para álbumes personales. El espacio compartido usa el
  prefijo `SYNO.FotoTeam` cuando el endpoint correspondiente está disponible.
  Los listados se limitan a 50 por solicitud y no hacen recorridos recursivos.
- La miniatura personal observada usa
  `/synofoto/api/v2/p/Thumbnail/get`; el espacio compartido se intenta solo
  mediante su API dinámica. La sesión, cookie `id` y `X-Syno-Token` permanecen
  en el backend. Las miniaturas se sirven mediante PhotoBridge; no se envían
  SID ni cookies al navegador. No se afirma que `X-Syno-Hash` sea necesario.
- `SYNO.Foto.Download` se anuncia en algunos manifiestos, pero su contrato no
  ha sido investigado ni se inició una descarga; no se declara habilitado ni
  validado en PhotoBridge.
- Descargar originales en streaming con el servicio existente, staging `.part`,
  SHA-256 local, validación de tamaño informado por la biblioteca, confirmación
  manual, límites del modo prueba e informe JSON. El hash local no demuestra
  igualdad criptográfica remota.
- No inferir una ruta File Station a partir del ID de Synology Photos. El
  staging de Photos usa `SynologyPhotos/<espacio>/<id_carpeta>/<nombre>` hasta
  que exista una resolución física inequívoca.
- Mantener interfaces HTTP y plantillas fuera del adaptador y los servicios
  de aplicación, siguiendo **TOOLS FIRST, AI SECOND**. No añadir LLM, MCP,
  skills ni Copilot SDK.

## Evidencia consultada y estatus

- **Oficial:** guía de DSM Login y guía de File Station. Cubren autenticación
  general y File Station, pero no especifican las API Synology Photos.
- **Interno/no documentado:** `SYNO.Foto.*`, `SYNO.FotoTeam.*`, sus métodos y
  los contratos de listado, miniaturas y descarga. Su presencia en
  `SYNO.API.Info` prueba que el NAS los anuncia, no que Synology garantice su
  compatibilidad.
- Referencias comunitarias consultadas:
  [zeichensatz/SynologyPhotosAPI](https://github.com/zeichensatz/SynologyPhotosAPI),
  [N4S4/synology-api](https://github.com/N4S4/synology-api) y
  [pmilano1/synology-dsm-api](https://github.com/pmilano1/synology-dsm-api).
  Estas fuentes corroboran los nombres y los parámetros usados, pero no son
  documentación oficial ni sustituyen una validación contra el NAS del usuario.

## Consecuencias y limitaciones

- La biblioteca Photos es preferente solo cuando el descubrimiento y las
  comprobaciones de lectura lo permiten; File Station permanece accesible.
- Los filtros de nombre, extensión y tipo se aplican sobre la página recibida;
  no se escanea la biblioteca para buscar coincidencias globales.
  `SimilarItem.list` se observó con `offset`, `limit`, `start_time`,
  `end_time` y `additional`; no se asumen parámetros de filtrado no observados.
  `time` se presenta como fecha de captura solo cuando Synology Photos la
  devuelve; no se sustituye por la fecha de modificación.
- El soporte de miniaturas puede variar por formato y versión DSM. Un elemento
  sin `cache_key` o con miniatura no disponible conserva un icono genérico.
- Las respuestas de API pueden cambiar entre versiones DSM. Los contratos
  simulados prueban el comportamiento implementado, no compatibilidad real.
- Las APIs internas de biblioteca y miniaturas fueron observadas en DSM real,
  pero el conector, los permisos, carpetas/álbumes y miniaturas de PhotoBridge
  siguen pendientes de validación manual. No se descargaron originales.
- La observación detallada de endpoints y payloads anonimizados se conserva en
  [`SYNOLOGY-PHOTOS-API.md`](../SYNOLOGY-PHOTOS-API.md).
