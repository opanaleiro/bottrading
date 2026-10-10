# Vector: ver al bot operar con precios reales

Puedes observar qué compraría o vendería el bot y cuánto ganaría o perdería **con cotizaciones reales de Kraken y dinero ficticio**. A esto se le llama *paper trading*. No necesitas depositar dinero ni conectar una cuenta de exchange.

## La configuración para empezar

| Ajuste | Valor | Qué significa |
| --- | --- | --- |
| Cotizaciones | Kraken | Precios públicos del mercado real. |
| Capital inicial | 10.000 USD virtuales | El saldo sirve para medir la simulación. |
| Modo | Operar | Permite abrir y cerrar posiciones simuladas. |
| Agresividad | 4 de 10 | Punto de partida moderado para observar la estrategia. |
| Máximo configurado | 3 posiciones | Hasta **3 simultáneas**; puede hacer más operaciones a lo largo del tiempo. |
| Límite diario | 3 % | Si detecta esa pérdida respecto al patrimonio inicial del día, cierra y bloquea entradas hasta el siguiente día UTC. |
| Espera entre análisis | 60 segundos | Termina un análisis, espera 60 segundos y empieza el siguiente. Obtener los datos lleva tiempo adicional. |
| Claude | Desactivado | Usa reglas técnicas, sin llamadas ni coste de API de IA. |

En el panel comprueba que pone **«KRAKEN · COTIZACIONES REALES»**. Si pone «DEMO», estás viendo precios inventados para probar la aplicación.

## Encenderlo y observarlo

En **Windows**:

1. Descarga el ZIP y usa **«Extraer todo»**. Abre la carpeta extraída: no ejecutes el programa dentro del archivo comprimido.
2. Si no tienes Python 3.12, instálalo desde el [instalador oficial de Python 3.12 para Windows](https://www.python.org/downloads/release/python-31210/). Elige el instalador de 64 bits para un Windows habitual de 64 bits. Durante la instalación, marca **«Add python.exe to PATH»**.
3. Haz doble clic en **`INICIAR_WINDOWS.bat`**. La primera vez instala las dependencias gratuitas y necesita internet; espera a que termine. Se abre una ventana de consola y después tu navegador con el panel.
4. Una cuenta nueva empieza con Kraken, Claude desactivado y el bot **pausado**. Pulsa **«Iniciar bot»** para comenzar los análisis automáticos. La primera carga de Kraken puede tardar unos 20 segundos o más. Deja abierta la consola, con el ordenador encendido, conectado a internet y sin suspensión.
5. Mira **«Mercado»**: al seleccionar una moneda verás la señal, sus indicadores y las razones para admitir o bloquear una entrada. En **«Posiciones abiertas»** aparecen dirección, entrada, precio actual, importe virtual, stop, objetivo y beneficio o pérdida provisional. **«Actividad»** guarda las operaciones cerradas con su resultado neto y el registro de decisiones. La curva de patrimonio muestra cómo cambia el conjunto de la cuenta.

| Tu ordenador | Lanzador |
| --- | --- |
| Windows | Doble clic en `INICIAR_WINDOWS.bat`. |
| macOS | `INICIAR_MACOS.command`. |
| Linux | `INICIAR_LINUX.sh`. |
| Cualquier sistema, desde una terminal | Ejecuta `python run_bot.py` desde la carpeta del proyecto; si tu sistema utiliza `python3`, usa ese nombre. |

Si el navegador no se abre, entra en `http://127.0.0.1:8000` en **el ordenador donde arrancaste el programa**. Esa dirección solo funciona allí: la dirección local de un servidor en Codex cloud no abre el panel en tu ordenador. Si el lanzador indica que falta Python, instala la versión indicada y vuelve a abrirlo.

Si ya usabas esta aplicación, el lanzador conserva tu cuenta y sus ajustes: comprueba la etiqueta Kraken antes de empezar. **Cerrar solo el navegador no detiene el bot**. Para cerrar el programa, pulsa **Ctrl+C en la consola**: se guardan los datos y deja de vigilar los stops. Cuando vuelvas a abrirlo, el bot estará pausado.

No tiene que entrar en cada análisis. Solo abre una posición cuando coinciden los indicadores y el riesgo lo permite; tampoco duplica posiciones de la misma moneda. Esperar también es una decisión del bot. Los indicadores utilizan velas de 15 minutos, aunque las cotizaciones se consultan en cada análisis; esto no es trading de alta frecuencia.

## Cómo decide y qué significan las operaciones

Busca coincidencia entre tendencia, impulso del precio y RSI. Después calcula el tamaño de la operación, un stop de pérdida y un objetivo de beneficio, respetando el saldo y los límites. La **«confianza»** mide coincidencia de indicadores: un 80 % no significa un 80 % de probabilidad de ganar.

- **Largo / long:** simula una compra; gana si el precio sube y pierde si baja.
- **Corto / short:** simula apostar por una bajada; gana si baja y pierde si sube. Es un modelo contable ficticio, sin préstamo real, financiación ni apalancamiento.
- **Stop:** nivel en el que intenta cerrar una posición para limitar pérdidas.
- **Objetivo:** nivel en el que intenta cerrar para recoger ganancias.

Stops y objetivos se comprueban durante los análisis. No son órdenes enviadas a Kraken: entre análisis un salto de precio puede hacer que la pérdida supere el stop o el límite diario previsto. Si falla Kraken, el panel muestra un error; el bot no cambia a datos demo para continuar.

## Cómo leer las ganancias y pérdidas

**Patrimonio virtual** es el efectivo disponible más el dinero reservado para las posiciones y su ganancia o pérdida provisional. Que el efectivo baje al abrir una posición no significa que hayas perdido todo el importe invertido: queda reservado para esa operación.

El **P&L** de una posición abierta es un resultado provisional al último precio consultado. No descuenta las comisiones ni el deslizamiento del futuro cierre; el precio de entrada sí incorpora su deslizamiento. El patrimonio de la cuenta ya refleja la comisión pagada al entrar. En **«Actividad»**, el P&L neto de una operación cerrada ya descuenta las comisiones y el deslizamiento simulados. No vuelvas a restarle la columna de comisiones.

La simulación aplica una comisión del **0,10 % al entrar y al salir**, y un precio de ejecución un **0,05 % peor en cada lado**. Ese empeoramiento se llama deslizamiento. Son supuestos del simulador, no una reproducción de tus tarifas reales en Kraken. Una operación con dinero real podría ejecutarse a otro precio y tener otro resultado.

Ejemplo de cálculo, **no resultados del bot**: una compra virtual de unos 1.000 USD que sale tras una subida del 1 % produciría unos 10 USD brutos. Tras aproximadamente 3 USD de costes de entrada y salida, quedarían **unos +7 USD**. Con una bajada del 1 %, serían unos −10 USD brutos y **unos −13 USD** tras costes. Los importes exactos varían con los precios y el tamaño ejecutados.

**Resultado de hoy** incluye operaciones cerradas y cambios de valor de las abiertas, según el día UTC que muestra el panel. **Drawdown** indica cuánto ha bajado el patrimonio desde su mayor valor registrado. Varias operaciones favorables no demuestran que la estrategia vaya a ganar en el futuro.

## Pausar, cerrar y reiniciar

- **Pausar bot:** detiene los análisis automáticos y la vigilancia de stops; deja las posiciones abiertas. Puedes hacer una ronda manual con **«Analizar ahora»** mientras está pausado.
- **Solo cierre:** bloquea nuevas entradas y cierra todas las posiciones en el siguiente análisis, con cotizaciones recientes. Para que ocurra ese cierre, mantén el bot activo o pulsa «Analizar ahora» si está pausado.
- **Cerrar** en una posición: pide una cotización reciente y cierra esa operación simulada.
- **Reiniciar simulación:** con el bot pausado, borra posiciones e historial y repone el capital virtual. Conserva Kraken y los ajustes de estrategia que habías elegido.

Los datos se guardan en la base local y se conservan cuando se reinicia el servidor. **El bot vuelve pausado tras ese reinicio**: debes pulsar «Iniciar bot» otra vez.

## Claude, ChatGPT y dejarlo funcionando solo

**Claude** es una IA de Anthropic; **cloud** significa una máquina remota. Que Claude esté desactivado solo significa que el bot decide mediante sus reglas técnicas. Las consultas públicas de Kraken no requieren claves y esta configuración no consume una API de IA ni tus mensajes de ChatGPT.

La automatización la hace **el programa en el servidor**, no esta conversación. Una vez iniciado, no necesita que ChatGPT le vaya dando instrucciones y puedes cerrar el panel sin detenerlo, siempre que el proceso del servidor siga funcionando. Dejar abierta una pestaña de ChatGPT no garantiza que su entorno continúe disponible.

En tu ordenador, necesita que el ordenador permanezca encendido, conectado a internet y sin suspensión, y que el servidor siga en marcha. Para funcionar día y noche necesita una máquina o un servicio de alojamiento que permanezca activo, con arranque, acceso y supervisión configurados; puede tener un coste de alojamiento. El entorno de trabajo de Codex no debe darse por un alojamiento permanente. El panel actual está pensado para acceso local y necesita autenticación antes de publicarlo en internet.

Claude queda opcional para más adelante y su API tendría un coste independiente de ChatGPT. No envíes claves por el chat. Esta versión tampoco descarga noticias automáticamente ni aprende o modifica su estrategia sola; el laboratorio resume los resultados que va registrando.

Para detalles técnicos y limitaciones, consulta [README.md](README.md).
