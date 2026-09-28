# ⛽ gasolineras-telegram

A bot that posts daily updates on the cheapest gas stations by municipality in Spain on a Telegram channel.

[🇪🇸 Español](README.es.md)

## Setup
1. Install deps: `python3 -m pip install -r requirements.txt`
2. Copy secrets: `cp .env.example .env` and fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`.
3. Copy config: `cp config.example.json config.json` and adjust `province_id` and `municipality_id` if needed.

## Configuration (`config.json`)
- `province_id`, `municipality_id`: where to search.
- `top_n_stations`: how many cheapest stations to send.
- `daily_hour`, `daily_minute`: daily run time.
- `log_file`: log path, relative or absolute.
- `skip_ssl_verification`: `false` by default. Set `true` only for testing with broken certs.

## Finding IDs
- Province: `GET https://geoportalgasolineras.es/geoportal/rest/getProvincias`
- Municipality: `POST https://geoportalgasolineras.es/geoportal/rest/getMunicipios` with `idProvincia=XX` as urlencoded form.

## Run
- Once: `python3 gas_prices_bot.py --run-once`
- Scheduler: `python3 gas_prices_bot.py`
- Custom config: `python3 gas_prices_bot.py --config /path/to/config.json`

## See it in action
[@gasolineras_sevilla on Telegram](https://t.me/gasolineras_sevilla)
