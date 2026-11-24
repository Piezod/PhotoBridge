# ADR 0002: Conexión y descarga de solo lectura desde Synology

- Estado: aceptada para la fase 1.
- Nota de evolución: la resolución controlada del alias QuickConnect y las
  excepciones al rechazo de redirecciones se especifican en ADR 0003; las
  peticiones API/autenticación continúan sin seguir redirecciones.
- Contexto: PhotoBridge necesita validar de forma manual y acotada la lectura
  de fotografías desde Synology DSM sin alterar los originales ni asumir
  APIs/versiones disponibles.

## Decisión

- Implementar un adaptador HTTPX que descubre rutas/versiones por
  `SYNO.API.Info` y utiliza las APIs oficiales Auth y File Station anunciadas.
- Mantener autenticación y cookies DSM en memoria del servidor. Guardar
  contraseñas únicamente si el usuario lo solicita y mediante keyring.
- Restringir a HTTPS con verificación de certificados, CA local opcional y sin
  seguir redirecciones.
- Exigir selección y confirmación manual; limitar cada operación a 10
  fotografías, 250 MB (250.000.000 bytes) y una descarga simultánea.
- Descargar con streaming a un temporal `.part`, validar tamaño, calcular hash
  local y guardar informe JSON. No declarar integridad criptográfica remota sin
  un hash de origen comparable.
- Mantener operaciones y sesiones en memoria; la fase no incorpora cola ni
  recuperación tras reinicio.

## Consecuencias

- Las pruebas pueden verificar protocolo y límites mediante mocks, pero no
  acreditan compatibilidad con un NAS real; el usuario debe validar
  manualmente su DSM, permisos y formatos.
- QuickConnect no se considera un endpoint directo garantizado para File
  Station. La interfaz solicita una URL DSM/DDNS o VPN accesible.
- Una descarga cancelada o una sesión perdida requiere revisión manual; no se
  reintenta automáticamente.
- Las cuentas remotas no reciben operaciones de escritura ni borrado.
