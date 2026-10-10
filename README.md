# Vector · Trading Lab

Bot de **simulación** con panel en español, inspirado en la descripción del vídeo. Analiza 16 criptomonedas, propone longs y shorts ficticios, aplica límites de riesgo y registra resultados. **No conecta una cuenta de exchange ni envía órdenes reales.**

## Iniciar

En **Windows**, extrae el ZIP y abre **INICIAR_WINDOWS.bat**. Necesitas Python 3.12 instalado. El lanzador instala las dependencias la primera vez y abre el panel en tu navegador; las cuentas nuevas usan precios públicos de Kraken, 10.000 USD ficticios y Claude desactivado. Pulsa «Iniciar bot» en el panel. Deja abierta la ventana del programa y evita que el ordenador entre en suspensión. Cerrar ChatGPT no detiene el bot; cerrar el programa sí.

La [guía rápida](GUIA_RAPIDA.md) explica los pasos y los resultados sin conocimientos técnicos. El lanzador local no publica un sitio en internet: el navegador y el programa se ejecutan en tu ordenador.

Para instalación manual o desarrollo:

Python 3.12. Desde la carpeta del proyecto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --requirement requirements.lock
.venv/bin/python -m unittest discover -s tests -v
bash scripts/start.sh
```

Abre el panel en el navegador del equipo donde ejecutas el servidor, puerto 8000. La cuenta comienza pausada con 10.000 USD ficticios. «Analizar ahora» analiza y ejecuta una ronda; «Iniciar bot» repite el análisis automáticamente y espera 60 segundos después de cada ciclo. La recogida y análisis de datos añaden tiempo: no es trading de alta frecuencia. El servidor se mantiene local: para publicarlo hay que añadir autenticación y un despliegue adecuado.

En Codex cloud, las instrucciones de instalación y arranque se guardan en la configuración del entorno. Una comprobación local de la API valida el servicio; los enlaces de previsualización de localhost no están disponibles en el flujo de onboarding.

## Usar el panel

- **Demo**: precios sintéticos reproducibles. Cada ciclo adelanta una vela ficticia de 15 minutos; no corresponde al tiempo real ni mide rentabilidad esperable.
- **Kraken**: cotizaciones spot públicas y velas de 15 minutos; no requiere claves. Permite simular operaciones sobre precios reales. Requiere acceso HTTPS a `api.kraken.com`. La primera carga puede tardar unos 20 segundos porque se evita saturar la API pública. Si faltan datos de un activo, se cancela el ciclo entero. Nunca se sustituyen silenciosamente precios reales por demo.
- **Operar**: permite entradas y cierres. **Solo cierre**: liquida las posiciones ficticias en el siguiente ciclo con cotizaciones recientes y bloquea nuevas entradas.
- **Agresividad 1–10**: ajusta el umbral técnico, el presupuesto de riesgo, el tamaño máximo y la cantidad admisible de posiciones. El motor mantiene límites adicionales aunque el panel permita un máximo mayor.
- **Pausar**: detiene el análisis; los stops dejan de vigilarse. Las órdenes stop son comprobaciones del simulador en cada ciclo, no órdenes alojadas en un exchange. Un salto de precio puede superar el riesgo previsto.
- **Reiniciar cuenta**: borra únicamente la cuenta de simulación, posiciones e historial de esta aplicación. Pide confirmación en el panel. Pausa antes de reiniciar. Para cambiar entre demo y Kraken, reinicia la cuenta primero; los historiales se mantienen separados.

Reiniciar conserva la fuente y los límites que hayas elegido. Los lanzadores nuevos usan Kraken por defecto; una cuenta guardada conserva su configuración anterior. `BOT_INITIAL_SOURCE=demo` o `kraken` permite elegir la fuente inicial al arrancar manualmente; esta variable nunca cambia una cuenta existente.

Se simula una comisión del **0,10 % por lado** y deslizamiento del **0,05 % por lado**. Las posiciones long y short reservan el nominal completo como colateral ficticio; no se usa apalancamiento. Los shorts son un modelo contable sintético: no reproducen financiación, préstamo, funding ni liquidaciones reales. Un salto extremo de precio puede superar el stop y el colateral de un short, generando un déficit. La simulación conserva esa pérdida y se detiene si el patrimonio es no positivo; no recorta artificialmente las pérdidas.

El límite diario por defecto es el 3 % de la cuenta: al alcanzarlo durante un ciclo se cierran las posiciones y se bloquean entradas hasta el siguiente día UTC. Se comprueban también los costes previstos antes de cada entrada. El saldo inicial diario se toma en el primer ciclo de cada día; no se dispone de una cotización histórica exacta a medianoche. La posición se valora a mercado; su PnL no realizado no descuenta todavía el coste del futuro cierre. El PnL de una operación cerrada sí incluye ambas comisiones y el deslizamiento.

## Qué análisis existe

El motor calcula EMA 12/26, RSI 14, momentum y volatilidad de retornos. «Confianza» expresa coincidencia de indicadores, **no probabilidad de ganar**. El control de riesgo siempre se aplica después de la señal; no se duplica una posición por activo ni se reabre un activo en el mismo ciclo en que se ha cerrado.

El recorrido del panel muestra cada etapa y su estado real. Derivados, DEX, blockchain, sentimiento y macro aparecen **sin proveedor conectado**. No se inventan esos datos. El campo de noticias admite contexto escrito por el usuario y se marca como no verificado; esta versión no descarga ni verifica noticias automáticamente.

El laboratorio agrupa operaciones long y short para observar hipótesis. Exige al menos 30 cierres antes de mostrar una indicación favorable o desfavorable. Eso sigue siendo evidencia descriptiva, sin prueba fuera de muestra: **no aprende ni modifica la estrategia de forma autónoma**, y no demuestra una ventaja rentable. El vídeo no entrega su estrategia ni permite reproducir su afirmación de ingresos diarios.

## Claude opcional

Funciona sin IA, sin claves y sin coste de API. Para activar Claude más adelante, inyecta `ANTHROPIC_API_KEY` como variable segura del proceso y permite `api.anthropic.com`. No escribas la clave en el chat, el panel, el código ni Git. El archivo `.env.example` documenta los nombres; `.env` no se carga automáticamente.

El modelo por defecto es `claude-sonnet-4-5-20250929`; se puede cambiar mediante `ANTHROPIC_MODEL`. Al activar IA, Claude puede vetar las entradas técnicamente admisibles; no puede saltarse los límites de riesgo, abrir operaciones por su cuenta ni verificar noticias externas. Una respuesta inválida o un error bloquea esa entrada. Se permiten como máximo tres llamadas por ciclo; esas llamadas **pueden generar cargos de API** y no hay límite de gasto mensual implementado. Las salidas y stops no dependen de la IA. No se ha validado esta integración contra la API real sin credenciales; sí se prueba su tratamiento de errores.

## Datos, API y pruebas

Estado persistente: `.local/paper.sqlite3` (SQLite), ignorado en Git. Puede cambiarse con `BOT_DB_PATH`. Las cuentas y operaciones sobreviven al reinicio del servidor; el bot arranca pausado. Se retienen los últimos 1.500 puntos de patrimonio, 150 eventos y 20 textos manuales. El historial de cierres se conserva completo. Usa un solo proceso de Uvicorn; varias instancias sobre la misma base no están soportadas.

Endpoints principales: `GET /api/state`, `GET /api/health`, `POST /api/cycle`, `/api/start`, `/api/stop`, `/api/settings`, `/api/reset`, `/api/news` y `/api/positions/{id}/close`. Solo existe el modo `paper`.

Las pruebas verifican señales, tamaños de riesgo, cierre long/short, contabilidad con costes, persistencia, bloqueos y contratos de la API. Kraken se prueba con respuestas controladas; una prueba con datos reales necesita que la política de red permita su dominio. Esta versión no incluye backtesting fuera de muestra, análisis automático de noticias ni ejecución con dinero real.
