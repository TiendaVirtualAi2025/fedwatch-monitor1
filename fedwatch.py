import os
import re
import json
import requests
from cme_fedwatch import get_probabilities

THRESHOLD = 65.0
NTFY_TOPIC = os.environ["NTFY_TOPIC"]


def rate_midpoint(rate_range):
    numbers = re.findall(r"\d+(?:\.\d+)?", rate_range)

    if len(numbers) != 2:
        raise ValueError(f"Rango inválido: {rate_range}")

    return (float(numbers[0]) + float(numbers[1])) / 2


def send_notification(title, message):
    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    response = requests.post(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": "high",
            "Tags": "chart_with_upwards_trend",
        },
        timeout=20,
    )

    response.raise_for_status()


def main():
    print("Consultando FedWatch...")

    data = get_probabilities("next")

    print(json.dumps(data, indent=2))

    meetings = data.get("meetings", [])

    if not meetings:
        raise RuntimeError("FedWatch no devolvió reuniones.")

    meeting = meetings[0]

    meeting_date = meeting["date"]
    probabilities = meeting["probabilities"]
    current_target = data["current_target"]

    current_mid = rate_midpoint(current_target)

    alerts = []

    for target_range, probability in probabilities.items():

        probability = float(probability)

        if probability < THRESHOLD:
            continue

        target_mid = rate_midpoint(target_range)

        if target_mid > current_mid:
            direction = "🔴 ALZA"
        elif target_mid < current_mid:
            direction = "🟢 RECORTE"
        else:
            direction = "⚪ MANTENER"

        alerts.append(
            f"{direction}: {target_range} → {probability:.1f}%"
        )

    if not alerts:
        print(f"No hay probabilidades >= {THRESHOLD}%.")
        return

    message = (
        f"FEDWATCH ALERTA\n\n"
        f"Próxima reunión: {meeting_date}\n"
        f"Tasa actual: {current_target}\n\n"
        + "\n".join(alerts)
        + f"\n\nUmbral configurado: {THRESHOLD}%"
    )

    print(message)

    send_notification(
        f"FedWatch > {THRESHOLD}%",
        message
    )

    print("✅ Notificación enviada a ntfy.")


if __name__ == "__main__":
    main()