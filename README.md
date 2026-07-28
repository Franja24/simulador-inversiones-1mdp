# Reto Actinver Tracker

MVP en Python para registrar y analizar un portafolio **simulado** del Reto
Actinver, con capital inicial predeterminado de $1,000,000 MXN.

> La información y los cálculos son exclusivamente informativos. No constituyen
> asesoría financiera, no prometen rendimientos y la aplicación no ejecuta
> operaciones reales.

## Alcance implementado (Fases 1, 2, 3 y 4)

- Creación persistente de portafolios.
- Registro manual de compras y ventas.
- Validación de efectivo y títulos disponibles.
- Posiciones reconstruidas desde el historial.
- Efectivo, costo promedio ponderado, utilidad realizada y no realizada.
- Advertencia por concentración máxima.
- Auditoría de operaciones y dashboard inicial en español.
- Pruebas unitarias del núcleo.
- Historial persistente de precios manuales.
- Dashboard ampliado con gráficas interactivas.
- Historial filtrable y descarga CSV.
- Importación validada y atómica desde CSV o XLSX.
- Plantillas descargables de importación.
- Reportes Excel con resumen, posiciones, operaciones, precios y reglas.
- Históricos OHLCV persistentes y disponibles sin conexión después de descargarse.
- Actualización incremental, detección de huecos y registro persistente `NO_DATA`.
- Proveedores desacoplados para Yahoo Finance, cache y extensiones futuras.
- Indicadores técnicos informativos con cache persistente.
- Benchmark configurable, dashboard de mercado y explorador de históricos.
- Actinver Quant Score explicable, ranking transversal y confianza separada.
- Régimen de mercado histórico y ajuste visible del score.
- Backtesting de ranking con ejecución D+1, costos y validación walk-forward.

`PortfolioService.valuation()` es la fuente de verdad para el valor vigente. El
campo persistido `Portfolio.current_value` es solo una caché compatible con la
Fase 1. Si no existe un precio manual, la valoración usa el costo contable de la
posición y la interfaz muestra la ausencia del precio.

## Requisitos

- Python 3.11 o superior.
- Windows 10/11 o macOS reciente.

## Instalación

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m scripts.init_db
streamlit run app.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m scripts.init_db
streamlit run app.py
```

Si no se ejecuta el inicializador, la aplicación crea las tablas y permite crear
el primer portafolio desde la interfaz.

## Calidad

```bash
pytest
ruff check .
mypy config database domain repositories services utils
```

## Costo promedio ponderado

Cada compra suma títulos y costo. El costo incluye precio por cantidad, comisión
e impuestos. El nuevo promedio es `costo acumulado / títulos`. Una venta parcial
retira del inventario la cantidad vendida al promedio vigente. Su utilidad
realizada es el ingreso de venta menos gastos de venta y menos ese costo liberado.
Las posiciones nunca dependen de cantidades capturadas manualmente.

## Estructura

- `app.py`: interfaz Streamlit mínima.
- `config/`: variables de entorno.
- `database/`: motor, modelos y creación del esquema.
- `domain/`: validación y objetos de dominio.
- `repositories/`: consultas y persistencia.
- `services/`: reglas de negocio y cálculos.
- `utils/`: cálculos, validación y logs.
- `scripts/init_db.py`: inicialización idempotente.
- `tests/`: pruebas unitarias.
- `data/`: base SQLite, logs e importaciones/exportaciones futuras.

## Configuración

Copie `.env.example` como `.env`. El archivo real se ignora en Git. Las variables
incluyen URL de base de datos, capital inicial, moneda, proveedor futuro y reglas
de concentración. SQLite persiste por defecto en `data/reto_actinver.db`.

`HISTORICAL_MARKET_PROVIDER` controla el proveedor histórico:

- `yahoo`: descarga mediante `yfinance`.
- `cache`: trabaja exclusivamente con información guardada.
- `future`: contrato de integración sin proveedor configurado.

## Arquitectura de inteligencia de mercado

```text
YahooProvider ─┐
CacheProvider ─┼─> MarketProvider ─> HistoryService ─> SQLite
FutureProvider ┘                              │
                                      IndicatorService
                                              │
                                  Mercado / Históricos UI
```

La UI consume servicios y nunca utiliza directamente las estructuras de
`yfinance`. Los DTOs `MarketQuote` y `MarketBar` normalizan cotizaciones, OHLC,
precio ajustado, volumen, dividendos, splits y timezone.

## Flujo de datos y cache

1. `HistoryService.missing_dates()` compara el rango solicitado con SQLite.
2. Solo se solicitan al proveedor los intervalos hábiles ausentes.
3. Una sesión esperada sin observación se marca `NO_DATA` para evitar consultas
   repetidas. La actualización forzada vuelve a consultar esas fechas.
4. `MarketHistoryRepository` evita duplicados por símbolo y fecha, actualiza
   correcciones OHLCV y rechaza barras imposibles antes de persistirlas.
5. Los datos sobreviven al reiniciar y `CacheProvider` permite consultarlos sin red.
6. Cada sincronización exitosa o fallida queda registrada de forma compacta.

El calendario base considera lunes a viernes y acepta exclusiones configurables.
No incluye todavía un calendario oficial de festivos de la BMV.

Las consultas múltiples devuelven éxitos y errores por símbolo, sin descartar un
lote completo por una emisora inválida. Yahoo se consulta con concurrencia
acotada y sus respuestas se normalizan antes de entrar al dominio.

## Indicadores

`IndicatorService` calcula SMA 5/10/20/50/100/200, EMA 5/9/20/50, RSI 14,
MACD/señal/histograma, ATR, Bandas de Bollinger, ADX, ROC, momentum, retornos,
volatilidad móvil, volumen relativo y niveles de 52 semanas. Son datos
informativos: no generan recomendaciones ni predicciones. El resultado se
reutiliza solo si coinciden última fecha, cantidad de filas, firma del histórico
y versión del algoritmo. RSI, ATR y ADX usan el suavizado de Wilder; una
corrección en precio o volumen invalida el cache aunque la última fecha no cambie.

## Benchmark

`BenchmarkService` usa la misma infraestructura que cualquier emisora. El valor
predeterminado para el S&P/BMV IPC es `^MXX`, pero el símbolo puede cambiarse en
la configuración del portafolio.

## Actualizar históricos

Abra **Históricos**, indique símbolo y rango, y pulse **Descargar o actualizar
histórico**. La pantalla permite visualizar OHLC, volumen, indicadores, calidad
de datos y exportar CSV.

## Agregar un proveedor

1. Implemente `providers.market_provider.MarketProvider`.
2. Devuelva exclusivamente `MarketQuote` y `MarketBar`.
3. Declare nombre, versión y mercados soportados.
4. Regístrelo en `providers/provider_factory.py`.
5. Añada pruebas offline con un cliente simulado.

## Migración y compatibilidad

Al iniciar, SQLAlchemy ejecuta `create_all`: agrega la tabla `manual_prices` si no
existe y conserva `portfolios`, `transactions` y `audit_logs`. Este mecanismo es
idempotente para tablas nuevas. El inicializador también aplica de forma
idempotente las columnas de firma y versión del cache de indicadores; una fase
posterior deberá incorporar Alembic para migraciones de esquema versionadas.

## Sesión BMV y precisión monetaria

El estado abierto/cerrado usa la zona `America/Mexico_City` y horario configurable
de 08:30 a 15:00. Es una estimación: no contempla festivos ni cierres
extraordinarios. Los históricos e indicadores se calculan como `float`; al cruzar
al dominio contable, `market_price_to_decimal()` convierte desde la representación
decimal del precio para mantener importes y cantidades en `Decimal`.

## Reglas consolidadas de Fases 1 y 2

- Las operaciones se validan en la capa de servicio contra las fechas de inicio y
  fin del reto. También se rechazan fechas futuras, con normalización consistente
  de timestamps con o sin zona horaria.
- La concentración usa el valor de mercado actual más el valor bruto de los
  títulos nuevos. Comisiones e impuestos afectan efectivo y costo contable, pero
  no se agregan al valor de mercado para esta regla.
- La valoración se recalcula después de un `flush` explícito. Cuando
  `commit=False`, el caller conserva el control total del commit o rollback.
- La antigüedad de precios considera lunes a viernes. Todavía no contempla los
  días festivos oficiales de la Bolsa Mexicana de Valores.

## Importación y reportes

La pantalla **Importar operaciones** ofrece plantillas CSV/XLSX, valida cada fila
y distingue duplicados contra la base de datos de duplicados dentro del archivo.
Los duplicados requieren autorización explícita tanto en la interfaz como en
`ImportService.execute(allow_duplicates=True)`. La simulación financiera se
detiene tras el primer error de negocio, aunque se siguen recopilando errores de
formato. Cualquier fallo de guardado revierte el lote completo.

La pantalla **Reportes** genera el archivo en `data/exports/`, permite descargarlo,
limita precios a emisoras del portafolio y presenta en la hoja `Reglas` el estado
general de cumplimiento.

## Comandos de calidad

```bash
pytest -v
pytest --cov=services --cov=repositories --cov=providers --cov=utils --cov-report=term-missing
ruff check .
mypy config database domain repositories services providers ui utils
```

## Actinver Quant Score (AQS)

El AQS ordena un universo local por fortaleza cuantitativa. No predice un precio
exacto ni produce instrucciones de operación. Cada resultado conserva fecha
efectiva, versión, score base, ajuste de régimen, score final, confianza,
clasificación, componentes, explicaciones y advertencias.

> El AQS es una herramienta cuantitativa informativa. No garantiza rendimientos
> y no constituye asesoría financiera.

La versión `aqs-1.0` utiliza estos pesos visibles en
`config/quant_score.py`:

| Factor | Peso |
|---|---:|
| Momentum ajustado 20 sesiones | 25% |
| Momentum ajustado 10 sesiones | 15% |
| Momentum ajustado 5 sesiones | 10% |
| Fortaleza relativa a benchmark (20 sesiones comunes) | 15% |
| Tendencia de medias/EMA/MACD | 10% |
| Confirmación de volumen | 10% |
| Riesgo por volatilidad, invertido | 10% |
| Cercanía no lineal al máximo reciente | 5% |

La fórmula base es:

```text
AQS_base = Σ(score_normalizado_factor × peso_factor)
AQS_final = limitar(AQS_base + ajuste_régimen, 0, 100)
```

El ajuste es opcional, siempre se muestra por separado y está limitado a ±10
puntos. Las clases son `MUY_FUERTE`, `FUERTE`, `POSITIVA`, `NEUTRAL`, `DÉBIL` y
`MUY_DÉBIL`; son etiquetas descriptivas, no recomendaciones.

### Normalización y confianza

Los factores se calculan con datos hasta la fecha efectiva, se winsorizan en los
percentiles configurados y se normalizan transversalmente. El método
predeterminado es `percentile_rank`, con empates promedio deterministas. También
está disponible `robust_zscore`, basado en mediana y MAD. La volatilidad se
invierte porque menor riesgo obtiene mejor score.

Un factor ausente no se rellena silenciosamente como neutral: aporta cero,
genera una advertencia y reduce la confianza. La confianza (0–100) combina
histórico disponible, factores calculables, frescura, huecos y tamaño del
universo. Por ello un AQS alto puede coexistir con confianza baja.

### Universo y persistencia

El universo puede definirse manualmente, desde símbolos con histórico local o
desde el portafolio. `quant_universe` permite activar/desactivar emisoras y
guardar empresa, sector y liquidez mínima. El benchmark se excluye del ranking.
La aplicación nunca descarga cientos de símbolos automáticamente.

Configuraciones, ejecuciones, resultados, componentes y regímenes se guardan por
versión. Una versión existente no puede cambiar de parámetros; cree un nuevo
`model_version` para comparar metodologías.

### Régimen

`MarketRegimeService` clasifica el benchmark como `BULLISH`, `BEARISH`,
`SIDEWAYS` o `INSUFFICIENT_DATA`, usando precio frente a SMA 20, relación
SMA 20/SMA 50, pendiente, volatilidad y drawdown. Alta volatilidad es un atributo
independiente, no una segunda etiqueta principal. El cálculo histórico corta
todos los datos en la fecha efectiva.

## Backtesting y walk-forward

El backtest recalcula el corte transversal en cada fecha de señal, elige el
`top_n` y ejecuta como mínimo en la apertura disponible de D+1. Mantiene durante
el horizonte configurado, aplica costos de entrada y salida y admite solamente
ponderación equal-weight en esta versión.

Compara AQS contra benchmark, universo equal-weight, selección aleatoria con
semilla reproducible, momentum de 20 sesiones y efectivo. Reporta rendimiento,
volatilidad, Sharpe y Sortino informativos, drawdown, hit rate, profit factor,
turnover, retorno relativo e information ratio.

El walk-forward separa ventanas de calibración y evaluación; los pesos permanecen
fijos y nunca se optimizan con el periodo fuera de muestra. La sensibilidad
prueba `top_n`, frecuencia y costos, y marca fragilidad cuando el resultado cambia
materialmente.

Para reproducir un backtest use el mismo universo, rango, versión, benchmark,
semilla, frecuencia, horizonte, costos y confianza mínima. La configuración JSON
exportada contiene esos parámetros.

### Prevención y limitaciones de sesgo

- No se entregan al score filas posteriores a la fecha efectiva.
- Una señal basada en el cierre D nunca usa ese mismo cierre como ejecución.
- No se inventan retornos con forward fill y el benchmark se alinea por fechas.
- Los costos no se omiten.
- Se advierte el posible sesgo de supervivencia del universo proporcionado.
- Los pesos no se eligen automáticamente usando todo el histórico.

La calidad del resultado depende de históricos locales completos y de que el
universo histórico refleje las emisoras realmente disponibles en cada fecha.
Todavía no se modelan delistings, deslizamiento intradía, profundidad de mercado,
impuestos ni acciones corporativas complejas.

Las pantallas **AQS** y **Backtesting** permiten calcular, explicar, comparar y
exportar ranking CSV, operaciones CSV y configuración JSON. El reporte Excel AQS
incluye resumen, ranking, componentes, régimen, histórico, backtest, comparación,
drawdown, operaciones, configuración y advertencias.

## Limitaciones y próximos pasos

No se permite editar o eliminar operaciones. Aún no se incluye un calendario
oficial de festivos BMV. No se implementan Monte Carlo, VaR, Expected Shortfall,
optimización avanzada, Machine Learning, predicciones, ejecución automática ni
recomendaciones financieras. `SimulationService` continúa reservado y no ejecuta
simulaciones.
