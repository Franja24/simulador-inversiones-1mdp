# Reto Actinver Tracker

MVP en Python para registrar y analizar un portafolio **simulado** del Reto
Actinver, con capital inicial predeterminado de $1,000,000 MXN.

> La información y los cálculos son exclusivamente informativos. No constituyen
> asesoría financiera, no prometen rendimientos y la aplicación no ejecuta
> operaciones reales.

## Alcance implementado (Fases 1 y 2)

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
benchmark histórico, Yahoo Finance, indicadores técnicos, watchlist, señales ni
métricas avanzadas. La integración externa y el análisis técnico corresponden a
la Fase 3.
