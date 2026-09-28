"""Daily gas price publisher via Telegram.

Fetches the cheapest gasoline and diesel stations from the official
Spanish government API and sends them in a single message to one
Telegram channel on a schedule.

Code, comments and logs are in English.
Telegram messages are in Spanish.
"""

import argparse
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    # Simple .env fallback.
    def load_dotenv(*args, **kwargs):
        try:
            with open(".env", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))
        except FileNotFoundError:
            pass
        return False


API_URL = "https://geoportalgasolineras.es/geoportal/rest/busquedaEstaciones"

# Product IDs from the API.
ID_PRODUCT_GASOLINE = "1"
ID_PRODUCT_DIESEL = "4"

REQUEST_TIMEOUT_SECONDS = 30

# Defaults, overridden by config.json.
DEFAULT_CONFIG = {
    "province_id": "41",
    "municipality_id": "6148",
    "top_n_stations": 5,
    "daily_hour": 18,
    "daily_minute": 0,
    "log_file": "gasolineras-telegram.log",
    "skip_ssl_verification": False,
}

# Active settings, updated by load_app_config().
PROVINCE_ID = DEFAULT_CONFIG["province_id"]
MUNICIPALITY_ID = DEFAULT_CONFIG["municipality_id"]
TOP_N_STATIONS = DEFAULT_CONFIG["top_n_stations"]
DAILY_HOUR = DEFAULT_CONFIG["daily_hour"]
DAILY_MINUTE = DEFAULT_CONFIG["daily_minute"]
LOG_FILE = DEFAULT_CONFIG["log_file"]
# True skips SSL checks. Insecure, use only for testing.
SKIP_SSL_VERIFICATION = DEFAULT_CONFIG["skip_ssl_verification"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def resolve_log_path(log_file: str, config_dir: Path) -> str:
    """Resolve log path. Relative paths go next to the config file."""
    path = Path(os.path.expanduser(log_file))
    if not path.is_absolute():
        path = config_dir / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def setup_logging(log_file: str) -> logging.Logger:
    """Set up file + console logging."""
    logger = logging.getLogger("gasolineras-telegram")
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


logger = logging.getLogger("gasolineras-telegram")
logger.addHandler(logging.NullHandler())


def apply_ssl_setting() -> None:
    """Mute warnings and log when SSL checks are skipped."""
    if SKIP_SSL_VERIFICATION:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except ImportError:
            pass
        logger.warning("SSL verification skipped (skip_ssl_verification=true).")


def load_app_config(config_path: Path) -> dict:
    """Load config.json and update active settings."""
    global PROVINCE_ID, MUNICIPALITY_ID, TOP_N_STATIONS
    global DAILY_HOUR, DAILY_MINUTE, LOG_FILE, SKIP_SSL_VERIFICATION
    settings = dict(DEFAULT_CONFIG)
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Config file not found at {config_path}, using defaults.")
        data = {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config {config_path}: must be a JSON object.")
    for key in DEFAULT_CONFIG:
        if key in data:
            settings[key] = data[key]
    # Cast and check values.
    try:
        settings["province_id"] = str(settings["province_id"])
        settings["municipality_id"] = str(settings["municipality_id"])
        settings["top_n_stations"] = int(settings["top_n_stations"])
        settings["daily_hour"] = int(settings["daily_hour"])
        settings["daily_minute"] = int(settings["daily_minute"])
        settings["log_file"] = str(settings["log_file"])
        settings["skip_ssl_verification"] = bool(settings["skip_ssl_verification"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid value in {config_path}: {exc}") from exc
    if not settings["province_id"] or not settings["municipality_id"]:
        raise ValueError("Config needs province_id and municipality_id.")
    if settings["top_n_stations"] < 1:
        raise ValueError("Config top_n_stations must be at least 1.")
    if not 0 <= settings["daily_hour"] <= 23:
        raise ValueError("Config daily_hour must be 0-23.")
    if not 0 <= settings["daily_minute"] <= 59:
        raise ValueError("Config daily_minute must be 0-59.")
    if not settings["log_file"]:
        raise ValueError("Config log_file must not be empty.")
    # Apply.
    PROVINCE_ID = settings["province_id"]
    MUNICIPALITY_ID = settings["municipality_id"]
    TOP_N_STATIONS = settings["top_n_stations"]
    DAILY_HOUR = settings["daily_hour"]
    DAILY_MINUTE = settings["daily_minute"]
    SKIP_SSL_VERIFICATION = settings["skip_ssl_verification"]
    config_dir = config_path.resolve().parent
    LOG_FILE = resolve_log_path(settings["log_file"], config_dir)
    settings["log_file"] = LOG_FILE
    return settings


def load_secrets() -> tuple[str, str]:
    """Load bot token and channel ID from the environment."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    missing = []
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not channel_id:
        missing.append("TELEGRAM_CHANNEL_ID")
    if missing:
        raise ValueError("Missing env vars: " + ", ".join(missing))
    return token, channel_id


def fetch_cheapest_stations(
    product_id: str, limit: int | None = None
) -> list[dict]:
    """Fetch stations and return the cheapest ones by price."""
    if limit is None:
        limit = TOP_N_STATIONS
    payload = {
        "tipoEstacion": "EESS",
        "idProvincia": PROVINCE_ID,
        "idMunicipio": MUNICIPALITY_ID,
        "idProducto": product_id,
        "eessEconomicas": True,
        "conPlanesDescuento": False,
        "tipoVenta": "P",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    logger.info("Requesting prices for product_id=%s", product_id)
    response = requests.post(
        API_URL,
        json=payload,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=not SKIP_SSL_VERIFICATION,
    )
    response.raise_for_status()
    data = response.json()

    raw_stations = data.get("estaciones", [])
    if not raw_stations:
        raise ValueError(f"No stations for product_id={product_id}")

    parsed: list[dict] = []
    for item in raw_stations:
        try:
            price = float(item.get("precio"))
        except (TypeError, ValueError):
            continue
        station = item.get("estacion", {}) or {}
        name = (station.get("rotulo") or "Desconocido").strip()
        address = (station.get("direccion") or "Desconocido").strip()
        postal_code = str(station.get("codPostal") or "").strip()
        municipality = (
            station.get("municipio") or station.get("provincia") or ""
        ).strip().upper()
        parsed.append(
            {
                "name": name,
                "address": address,
                "postal_code": postal_code,
                "municipality": municipality,
                "price": price,
            }
        )

    if not parsed:
        raise ValueError(f"No priced stations for product_id={product_id}")

    parsed.sort(key=lambda s: s["price"])
    cheapest = parsed[:limit]
    logger.info(
        "Found %d stations for product_id=%s, kept top %d",
        len(parsed),
        product_id,
        len(cheapest),
    )
    return cheapest


def format_price_spanish(price: float) -> str:
    """Format price as 1.759 -> '1,759'."""
    return f"{price:.3f}".replace(".", ",")


def format_location_spanish(station: dict) -> str:
    """Build 'ADDRESS, POSTAL MUNICIPALITY'."""
    location = station.get("address", "Desconocido")
    postal_code = station.get("postal_code", "")
    municipality = station.get("municipality", "")
    if postal_code or municipality:
        location += f", {postal_code} {municipality}".strip()
    return location.strip()


def escape_markdownv2(text: str) -> str:
    """Escape MarkdownV2 reserved characters."""
    text = text.replace("\\", "\\\\")
    for ch in "_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _station_lines(stations: list[dict]) -> list[str]:
    """Format station entries. Only dynamic data is escaped."""
    lines: list[str] = []
    for station in stations:
        # Price is digits + comma only, safe.
        price = format_price_spanish(station["price"])
        name = escape_markdownv2(station["name"])
        lines.append(f"*{name}* — {price} €/L")
        lines.append(f"📍 {escape_markdownv2(format_location_spanish(station))}")
        lines.append("")
    return lines


def format_combined_message_spanish(
    gasoline: list[dict], diesel: list[dict], report_date: datetime.date
) -> str:
    """Build one Spanish message with both fuels (MarkdownV2)."""
    # Static labels have no reserved chars, so no escaping needed.
    # Only the link dot is pre-escaped below.
    date_str = report_date.strftime("%d/%m/%Y")  # digits + / only
    source_line = f"_Fuente: [geoportalgasolineras\\.es](https://geoportalgasolineras.es/geoportal-instalaciones/Inicio)_"
    lines = [
        f"*⛽ Gasolineras más baratas — {date_str}*",
        "",
        "",
        "*🟢 Gasolina 95*",
        "",
    ]
    lines.extend(_station_lines(gasoline))
    lines.append("")
    lines.append("*⚫ Gasóleo A*")
    lines.append("")
    lines.extend(_station_lines(diesel))
    lines.append("")
    lines.append(source_line)
    return "\n".join(lines).strip()


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    """Send text via the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    logger.info("Sending Telegram message to chat_id=%s", chat_id)
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=not SKIP_SSL_VERIFICATION,
    )
    # Read body first to keep Telegram's error description on 400s.
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code != 200 or (
        isinstance(payload, dict) and not payload.get("ok")
    ):
        logger.error(
            "Telegram request failed: status=%s chat_id=%s body=%s",
            response.status_code,
            chat_id,
            response.text[:2000],
        )
        raise ValueError(
            f"Telegram API error: HTTP {response.status_code}: {response.text[:2000]}"
        )
    logger.info("Message sent to chat_id=%s", chat_id)


def publish_daily_prices(token: str, channel_id: str) -> None:
    """Fetch both fuels and publish one message. Log errors, never post them."""
    today = datetime.date.today()
    try:
        gasoline = fetch_cheapest_stations(ID_PRODUCT_GASOLINE)
        diesel = fetch_cheapest_stations(ID_PRODUCT_DIESEL)
        message = format_combined_message_spanish(gasoline, diesel, today)
        send_telegram_message(token, channel_id, message)
    except Exception:
        logger.exception("Failed to publish daily prices")


def seconds_until_next_run(hour: int | None = None, minute: int | None = None) -> float:
    """Seconds until the next daily run."""
    if hour is None:
        hour = DAILY_HOUR
    if minute is None:
        minute = DAILY_MINUTE
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def run_scheduler(token: str, channel_id: str) -> None:
    """Run forever, publishing at the configured time."""
    logger.info(
        "Scheduler started. Daily publication at %02d:%02d local time.",
        DAILY_HOUR,
        DAILY_MINUTE,
    )
    while True:
        wait_seconds = seconds_until_next_run()
        next_run = datetime.datetime.now() + datetime.timedelta(seconds=wait_seconds)
        logger.info(
            "Next publication at %s (in %.0f seconds).",
            next_run.strftime("%Y-%m-%d %H:%M:%S"),
            wait_seconds,
        )
        time.sleep(wait_seconds)
        logger.info("Running scheduled publication.")
        publish_daily_prices(token, channel_id)
        # Avoid a double run inside the same minute.
        time.sleep(60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish daily gas prices to Telegram on a schedule."
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Publish once and exit.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="JSON config path (default: config.json next to the script).",
    )
    args = parser.parse_args()

    try:
        settings = load_app_config(args.config)
    except Exception:
        print("Invalid app configuration. Check config file.", file=sys.stderr)
        return 1

    global logger
    logger = setup_logging(LOG_FILE)
    apply_ssl_setting()
    logger.info(
        "Config from %s: province=%s municipality=%s top_n=%d schedule=%02d:%02d log=%s skip_ssl=%s.",
        args.config,
        settings["province_id"],
        settings["municipality_id"],
        settings["top_n_stations"],
        settings["daily_hour"],
        settings["daily_minute"],
        settings["log_file"],
        settings["skip_ssl_verification"],
    )

    try:
        token, channel_id = load_secrets()
    except Exception:
        logger.exception("Invalid secrets. Check environment variables.")
        return 1

    if args.run_once:
        logger.info("Running one-time publication.")
        publish_daily_prices(token, channel_id)
        return 0

    try:
        run_scheduler(token, channel_id)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
