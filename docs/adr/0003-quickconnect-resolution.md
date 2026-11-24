# ADR 0003: Resolución segura de URL QuickConnect

- Estado: aceptada para corregir PB-002-FIX-001; validación real pendiente.
- Contexto: la conexión rechazaba todas las URLs QuickConnect antes de
  descubrir APIs DSM, aunque una URL corta puede redirigir a un endpoint
  regional. La fase 1 previa no había probado esta ruta con un NAS real.

## Decisión

- Aceptar URLs HTTPS `quickconnect.to/<ID>` y `quickconnect.cn/<ID>`, además de
  URLs regionales bajo esos dominios.
- Resolver el alias corto sin credenciales. Limitar redirecciones y aceptar
  únicamente destinos HTTPS dentro de los dominios QuickConnect y sus
  subdominios; rechazar destinos externos, credenciales en URL y downgrade a
  HTTP. Descartar cookies recibidas durante la resolución.
- Consultar `SYNO.API.Info` en el endpoint resuelto. Exigir que se anuncien
  `SYNO.API.Auth`, `SYNO.FileStation.List` y `SYNO.FileStation.Download` antes
  de leer credenciales guardadas o enviar credenciales introducidas.
- Mantener `follow_redirects=False` para las peticiones API y login. Ninguna
  credencial se reenvía en una redirección; las solicitudes de login solo se
  hacen al endpoint que superó el descubrimiento y la validación TLS.
- Mostrar errores QuickConnect diferenciados para destino no autorizado,
  redirección, HTML o ausencia de APIs. No presentar disponibilidad de API como
  validación de conexión real.
- Mantener intactas las conexiones directas por IP, DDNS y VPN.

## Consecuencias y limitaciones

- La resolución solo demuestra el comportamiento HTTP simulado en pruebas; la
  compatibilidad de relay/servicios QuickConnect depende de DSM y debe probarse
  manualmente por el usuario antes de considerarla validada.
- Una redirección fuera de los dominios de QuickConnect se rechaza incluso si
  el destino final pudiera ser un NAS legítimo. El usuario puede introducir
  directamente una URL DSM/DDNS o VPN de confianza en ese caso.
- No se añade ninguna URL personal fija ni se realiza una conexión real
  automáticamente.
