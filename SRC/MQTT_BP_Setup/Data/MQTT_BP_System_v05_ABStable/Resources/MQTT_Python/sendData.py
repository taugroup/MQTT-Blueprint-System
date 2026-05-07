import paho.mqtt.client as mqtt
import time
import os
import ast
import math

# -----------------------------
# Paths (relative to this file)
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTROL_PANEL_PATH = os.path.join(BASE_DIR, "controlPanel.txt")
DATA_FOLDER = os.path.join(BASE_DIR, "input_data")


# -----------------------------
# Load settings from controlPanel.txt
# -----------------------------
def load_control_panel(path: str) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"controlPanel.txt not found at: {path}")

    settings = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f.readlines():
            line = raw.strip()

            # Skip blanks and comments
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            try:
                parsed_value = ast.literal_eval(value)
            except Exception:
                parsed_value = value.strip("'\"")

            settings[key] = parsed_value

    return settings


cfg = load_control_panel(CONTROL_PANEL_PATH)

# Required settings
MQTT_BROKER = cfg.get("MQTT_BROKER")
MQTT_PORT = cfg.get("MQTT_PORT")
MQTT_TOPIC = cfg.get("MQTT_TOPIC")

# Optional settings (with defaults)
START_UP_DELAY = cfg.get("START_UP_DELAY", 0)  # seconds before sending begins (countdown)
MESSAGE_RATE = cfg.get("MESSAGE_RATE", 5)      # seconds between individual messages
ENABLE_LOOP = cfg.get("ENABLE_LOOP", 1)        # 1 = keep looping, 0 = send once then disconnect
LOOP_DELAY = cfg.get("LOOP_DELAY", 3)          # seconds between loops (only used if looping)

missing = [k for k in ("MQTT_BROKER", "MQTT_PORT", "MQTT_TOPIC") if cfg.get(k) is None]
if missing:
    raise ValueError(
        f"Missing required setting(s) in controlPanel.txt: {', '.join(missing)}\n"
        f"Expected lines like:\n"
        f"MQTT_BROKER = 'localHost'\nMQTT_PORT = 1883\nMQTT_TOPIC = 'dummyData'\n"
        f"START_UP_DELAY = 5\nMESSAGE_RATE = 0.001\nENABLE_LOOP = 1\nLOOP_DELAY = 0.001"
    )

# Type enforcement
try:
    MQTT_PORT = int(MQTT_PORT)
except Exception as e:
    raise ValueError(f"MQTT_PORT must be an integer, got: {MQTT_PORT!r}") from e

def to_non_negative_float(name, value, default):
    if value is None:
        value = default
    try:
        f = float(value)  # supports 0.5, 0.2, 0.001, etc.
        if f < 0:
            raise ValueError
        return f
    except Exception as e:
        raise ValueError(f"{name} must be a non-negative number (seconds), got: {value!r}") from e

START_UP_DELAY = to_non_negative_float("START_UP_DELAY", START_UP_DELAY, 0)
MESSAGE_RATE = to_non_negative_float("MESSAGE_RATE", MESSAGE_RATE, 5)
LOOP_DELAY = to_non_negative_float("LOOP_DELAY", LOOP_DELAY, 3)

# ENABLE_LOOP: allow 0/1, "0"/"1", True/False
try:
    ENABLE_LOOP = int(ENABLE_LOOP)
except Exception as e:
    raise ValueError(f"ENABLE_LOOP must be 0 or 1, got: {ENABLE_LOOP!r}") from e
ENABLE_LOOP = 1 if ENABLE_LOOP != 0 else 0

print(
    f"[controlPanel] MQTT_BROKER={MQTT_BROKER}, MQTT_PORT={MQTT_PORT}, MQTT_TOPIC={MQTT_TOPIC}, "
    f"START_UP_DELAY={START_UP_DELAY}s, MESSAGE_RATE={MESSAGE_RATE}s, ENABLE_LOOP={ENABLE_LOOP}, LOOP_DELAY={LOOP_DELAY}s"
)

# -----------------------------
# Auto-detect CSV inside input_data
# -----------------------------
def get_csv_file() -> str:
    if not os.path.isdir(DATA_FOLDER):
        raise FileNotFoundError(f"input_data folder not found at: {DATA_FOLDER}")

    for file in os.listdir(DATA_FOLDER):
        if file.lower().endswith(".csv"):
            return os.path.join(DATA_FOLDER, file)

    raise FileNotFoundError("No CSV file found inside input_data folder")


FILE_PATH = get_csv_file()
print(f"Using CSV file: {FILE_PATH}")


# -----------------------------
# Startup countdown (NO MQTT publishing)
# -----------------------------
def startup_countdown(delay_seconds: float):
    if delay_seconds <= 0:
        return

    remaining = delay_seconds
    # Count down in whole-number display, but sleep accurately (supports fractions too)
    while remaining > 0:
        print(f"Starting in {int(math.ceil(remaining))}...")
        step = 1.0 if remaining >= 1.0 else remaining
        time.sleep(step)
        remaining -= step

    print("Starting now.")


# -----------------------------
# MQTT Setup
# -----------------------------
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected with result code {reason_code}")

def on_message(client, userdata, msg):
    print(msg.topic + " " + str(msg.payload))

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()


def publish_data_once():
    """Publish every non-empty line in the CSV once, with MESSAGE_RATE delay between lines."""
    with open(FILE_PATH, "r", encoding="utf-8") as file:
        for raw in file:
            message = raw.strip()
            if not message:
                continue

            client.publish(MQTT_TOPIC, payload=message, qos=0, retain=False)
            print(f"Published message: '{message}' to topic: '{MQTT_TOPIC}'")

            time.sleep(MESSAGE_RATE)


try:
    # ✅ countdown happens BEFORE sending any MQTT data
    startup_countdown(START_UP_DELAY)

    if ENABLE_LOOP == 1:
        while True:
            publish_data_once()
            time.sleep(LOOP_DELAY)
    else:
        publish_data_once()
        client.publish(MQTT_TOPIC, "Disconnect")
        print("ENABLE_LOOP=0 → Sent Disconnect and stopping.")

except KeyboardInterrupt:
    print("Stopped by user (Ctrl+C)")

finally:
    client.loop_stop()
    client.disconnect()
