# Arquitectura de PhotoBridge

## Alcance implementado

PhotoBridge es un monolito modular de ejecución local. La fase 1 incorpora
conexión manual, exploración paginada de solo lectura y descarga local
controlada desde Synology DSM. No implementa persistencia de operaciones,
reanudación tras reinicios, Amazon Photos ni migraciones.

## Capas

- `app/domain/models` y `app/domain/ports`: modelos de API, File Station,
  Synology Photos y descargas, y contrato de almacenamiento seguro de
  credenciales.
- `app/application/services`: orquestación de conexiones y descargas, límites
  de prueba, validación de selección y aplicación de reglas.
- `app/infrastructure/synology`: cliente HTTPX compartido para descubrimiento,
  autenticación y transporte; adaptadores separados para File Station y
  Synology Photos.
- `app/infrastructure/security`: adaptador keyring para credenciales
  recordadas.
- `app/presentation/api`, `templates` y `static`: rutas FastAPI, formularios,
  CSRF, vistas HTMX y recursos locales.
- `app/config.py`: configuración tipada con Pydantic Settings.

FastAPI compone los servicios en `app/main.py`. Los servicios reciben las
dependencias por constructor; las sesiones activas, selecciones y operaciones
son volátiles y residen en memoria.

## Integración Synology

La aplicación descubre rutas y versiones mediante `SYNO.API.Info` y utiliza
`SYNO.API.Auth`, `SYNO.FileStation.List`, `SYNO.FileStation.Download` y, si el
NAS la anuncia, `SYNO.FileStation.Thumb`. Las operaciones son manuales y de
solo lectura en el NAS. Listados limitados a 50 elementos y selección explícita
evitan escaneos recursivos.

La sesión DSM y sus cookies se quedan en el cliente HTTP del servidor. La
contraseña solo se conserva en memoria durante la operación, salvo que el
usuario opte por keyring. No se incluyen secretos en URLs, logs o informes.
Las peticiones usan HTTPS con verificación TLS y admiten una CA de confianza
configurada localmente.

Para una URL corta QuickConnect (`quickconnect.to/<ID>` o
`quickconnect.cn/<ID>`), el adaptador resuelve primero la redirección sin
credenciales. Solo acepta destinos HTTPS bajo esos dominios QuickConnect o sus
subdominios, limita la cadena de redirecciones y descarta las cookies obtenidas
durante la resolución. Una redirección a otro dominio, downgrade a HTTP o
redirección durante la petición de login se rechaza; HTTPX no sigue
redirecciones automáticamente. Una vez en el endpoint regional, PhotoBridge
consulta `SYNO.API.Info` y confirma que se anuncian Auth, File Station List y
Download antes de enviar credenciales. Si el destino devuelve HTML o JSON que
no corresponde a la API, se presenta un error específico y no se intenta el
login. Las URLs regionales directas también se aceptan y se comprueban igual.

Esto permite probar endpoints QuickConnect que publiquen la API DSM, pero no
garantiza que todos los métodos de conexión QuickConnect/relay admitan estas
APIs. La disponibilidad real depende de DSM, su configuración QuickConnect,
certificados y servicios permitidos, y requiere confirmación manual del
usuario.

### Synology Photos

Cuando está disponible, el explorador usa Synology Photos como vista
preferente; File Station permanece seleccionable como vista complementaria.
El adaptador separado `app/infrastructure/synology/photos.py` descubre las API
mediante `SYNO.API.Info` en `/photo/webapi/query.cgi` y usa las versiones y
rutas anunciadas. Comprueba acceso personal y compartido mediante llamadas de
listado acotadas; lista de forma paginada (máximo 50) y no recorre la
biblioteca recursivamente. Los álbumes se consultan solo en el espacio personal.

Synology Photos no tiene una guía oficial de API web. `SYNO.Foto.*` y
`SYNO.FotoTeam.*` son interfaces internas/no documentadas; los nombres de
API, métodos y parámetros se corroboraron con manifiestos y referencias
comunitarias, no con un contrato soportado por Synology. `SYNO.API.Info`
anuncia capacidades, pero no garantiza que cada método funcione en todas las
versiones DSM. Por eso cada capacidad se presenta como anunciada o accesible
solo según evidencia de descubrimiento y llamadas de lectura.

Las llamadas Photos reutilizan el cliente y la sesión DSM del servidor. El SID,
la cookie `id` y `X-Syno-Token` no se envían al navegador ni se registran.
Miniaturas y originales se sirven/transfieren a través del backend y solo con
las APIs Photos anunciadas. La selección de originales conserva los límites y
el servicio de descarga existente: confirmación manual, hasta 10 fotografías,
250 MB por operación, una transferencia, streaming, `.part`, tamaño, hash
local, cancelación y JSON local. No se afirma verificación de integridad remota
sin hash remoto comparable.

Un ID Photos no se interpreta como una ruta física de File Station. Mientras
no haya una resolución inequívoca, los originales Photos se guardan bajo
`data/downloads/<id_conexion>/SynologyPhotos/<espacio>/<id_carpeta>/`.
Los filtros de nombre, extensión y fecha se aplican sobre cada página
solicitada; no hacen una búsqueda global ni provocan escaneos. La fecha se
toma del campo temporal de Synology Photos, sin sustituirla por la fecha de
modificación. Véase [ADR 0004](adr/0004-synology-photos-adapter.md).

## Flujo y seguridad de descargas

1. El backend valida que cada ruta procede de una selección de archivos
   conocidos y que el elemento sigue siendo una fotografía permitida.
2. Comprueba confirmación manual, límites del modo prueba, espacio libre,
   ausencia de colisiones y disponibilidad de la API.
3. Vuelve a consultar tamaño/ruta remotos y descarga secuencialmente mediante
   streaming a un archivo `.part`, actualizando el progreso y calculando
   SHA-256 sin cargar el archivo completo en memoria.
4. Comprueba el tamaño descargado y publica el archivo sin sobrescribir un
   destino existente. Los errores y cancelaciones limpian el temporal cuando
   es seguro hacerlo.
5. Escribe un informe JSON local. El hash local no se considera prueba de
   integridad remota sin un hash de origen comparable.

La ubicación predeterminada es `data/downloads/<id_conexion>/<ruta_remota>/`;
los informes se guardan en la subcarpeta `.reports`. Los nombres incompatibles
con Windows, traversal y enlaces simbólicos en rutas de destino se rechazan.
Los archivos remotos nunca se modifican ni eliminan. La confirmación CSRF se
valida en las operaciones POST.

## Límites deliberados y siguientes pasos

- Modo prueba obligatorio: máximo 10 fotografías, 250 MB (250.000.000 bytes)
  por operación y una
  operación/descarga simultánea.
- QuickConnect se resuelve con restricciones HTTPS y las credenciales se
  envían solo tras descubrir las API requeridas. El usuario confirmó una
  conexión real, autenticación, File Station, APIs de descarga/miniaturas y
  permisos de lectura (3515 ms). Esto no valida una descarga real ni
  Synology Photos.
- La autenticación MFA requiere código introducido manualmente. No se elude
  MFA ni CAPTCHA.
- La sesión y el estado de descarga no sobreviven al reinicio. No hay cola,
  reintentos automáticos ni recuperación persistente en esta fase.
- No se declara verificación criptográfica contra el NAS si no hay hash remoto
  comparable.
- Synology Photos usa contratos internos/no documentados y continúa pendiente
  de prueba manual en el NAS. Miniaturas, búsquedas, álbumes, permisos de
  espacios y descargas pueden variar según versión; no se extrapola la
  validación de File Station a Photos.
- Amazon Photos, sincronización, borrado remoto y migración quedan fuera del
  alcance actual.

## Preparación para herramientas y agentes

La estrategia futura es **TOOLS FIRST, AI SECOND**. Los servicios de conexión,
exploración, descarga y subida viven en la capa de aplicación, reciben
dependencias por constructor y no dependen de FastAPI ni de plantillas; la
interfaz actual los invoca mediante rutas HTTP. Esto permite exponerlos en el
futuro como herramientas con entradas tipadas, límites backend y resultados
auditablemente verificables para Copilot SDK/skills. No se implementa IA ni se
añaden dependencias de agente en esta fase.

## Interfaz y ejecución

Bootstrap 5 y HTMX se sirven desde archivos locales; no se usan CDN. Uvicorn y
`scripts/start.ps1` enlazan el servidor a `127.0.0.1`. La aplicación no debe
exponerse a Internet.
