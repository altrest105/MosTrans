import json
import time
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen

BASE_URL = "http://127.0.0.1:8000"
INTERVAL_S = 2


def get_json(path: str) -> dict:
    with urlopen(f"{BASE_URL}{path}", timeout=2) as response:  # noqa: S310
        return json.load(response)


def main() -> None:
    """Наблюдать деградацию и восстановление во время ручного теста.

    Запустите скрипт, затем временно остановите NDTP-эмулятор или ML Service.
    Backend должен остаться доступен, перейти в degraded/stale и после
    восстановления источника снова вернуться в рабочее состояние.
    """

    print("Reliability watch запущен. Ctrl+C для остановки.")
    print("Теперь можно временно остановить NDTP или ML Service и затем включить обратно.\n")

    previous = None

    try:
        while True:
            stamp = datetime.now().strftime("%H:%M:%S")
            try:
                status = get_json("/system/status")
                metrics = get_json("/metrics")
                current = (
                    status.get("status"),
                    status.get("message"),
                    metrics.get("reliability", {}).get("recoveries"),
                )

                if current != previous:
                    print(
                        f"[{stamp}] status={status.get('status')} | "
                        f"last_known={status.get('last_known_state')} | "
                        f"recoveries={metrics.get('reliability', {}).get('recoveries')}"
                    )
                    print(f"          {status.get('message')}")
                    previous = current
            except URLError as exc:
                print(f"[{stamp}] Backend недоступен: {exc}")

            time.sleep(INTERVAL_S)
    except KeyboardInterrupt:
        print("\nReliability watch остановлен.")


if __name__ == "__main__":
    main()
