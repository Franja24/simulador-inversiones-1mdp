# Reto Actinver Tracker

MVP en Python para registrar y analizar un portafolio **simulado** del Reto
Actinver, con capital inicial predeterminado de $1,000,000 MXN.

> La información y los cálculos son exclusivamente informativos. No constituyen
> asesoría financiera, no prometen rendimientos y la aplicación no ejecuta
> operaciones reales.

## Alcance implementado (Fases 1, 2 y 3)

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
- Actualización incremental y detección de huecos en el cache local.
- Proveedores desacoplados para Yahoo Finance, cache y extensiones futuras.
- Indicadores técnicos informativos con cache persistente.
- Benchmark configurable, dashboard de mercado y explorador de históricos.

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
3. `MarketHistoryRepository` evita duplicados por símbolo y fecha.
4. Los datos sobreviven al reiniciar y `CacheProvider` permite consultarlos sin red.
5. Cada sincronización exitosa o fallida queda registrada de forma compacta.

Los huecos consideran lunes a viernes; todavía pueden señalar como faltantes los
festivos de la BMV.

## Indicadores

`IndicatorService` calcula SMA 5/10/20/50/100/200, EMA 5/9/20/50, RSI 14,
MACD/señal/histograma, ATR, Bandas de Bollinger, ADX, ROC, momentum, retornos,
volatilidad móvil, volumen relativo y niveles de 52 semanas. Son datos
informativos: no generan recomendaciones ni predicciones. El resultado se
reutiliza mientras no cambie la última fecha histórica.

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
idempotente para tablas nuevas, pero no modifica columnas existentes; una fase
posterior deberá incorporar Alembic para migraciones de esquema versionadas.

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

## Limitaciones y próximos pasos

No se permite editar o eliminar operaciones. Aún no se incluyen snapshots,
calendario de festivos BMV, watchlist ni señales. `QuantScoreService` y
`SimulationService` contienen únicamente contratos y DTOs: no implementan Quant
Score, Monte Carlo, IA, predicciones ni optimización del portafolio.
