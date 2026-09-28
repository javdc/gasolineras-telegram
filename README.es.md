# ⛽ gasolineras-telegram

Un bot que publica diariamente las gasolineras más baratas por municipio en un canal de Telegram.

## Instalación
1. Instala dependencias: `python3 -m pip install -r requirements.txt`
2. Copia secretos: `cp .env.example .env` y rellena `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHANNEL_ID`.
3. Copia la configuración: `cp config.example.json config.json` y ajusta `province_id` y `municipality_id` si hace falta.

## Configuración (`config.json`)
- `province_id`, `municipality_id`: dónde buscar.
- `top_n_stations`: cuántas gasolineras baratas se envían.
- `daily_hour`, `daily_minute`: hora de envío diaria.
- `log_file`: ruta del log, relativa o absoluta.
- `skip_ssl_verification`: `false` por defecto. Pon `true` solo para pruebas con certificados rotos.

## Encontrar IDs
- Provincia: `GET https://geoportalgasolineras.es/geoportal/rest/getProvincias`
- Municipio: `POST https://geoportalgasolineras.es/geoportal/rest/getMunicipios` con `idProvincia=XX` como formulario urlencoded.

## Uso
- Una vez: `python3 gas_prices_bot.py --run-once`
- Programado: `python3 gas_prices_bot.py`
- Otra configuración: `python3 gas_prices_bot.py --config /ruta/a/config.json`

## Míralo en acción
[@gasolineras_sevilla en Telegram](https://t.me/gasolineras_sevilla)
