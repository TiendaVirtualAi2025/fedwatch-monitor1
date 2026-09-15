import os
import requests
from cme_fedwatch import get_probabilities

THRESHOLD = 65.0
NTFY_TOPIC = os.environ["NTFY_TOPIC"]


def send_ntfy(message):
    response = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "🚨 FEDWATCH > 65%",
            "Priority": "high",
            "Tags": "warning"
        },
        timeout=20
    )

    response.raise_for_status()


def main():

    print("=" * 50)
    print("CME FEDWATCH MONITOR")
    print("=" * 50)

    print("Consultando FedWatch...")

    data = get_probabilities("next")

    print("Datos recibidos:")
    print(data)

    meetings = data.get("meetings", [])

    if not meetings:
        raise RuntimeError(
            "FedWatch no devolvió ninguna reunión."
        )

    meeting = meetings[0]

    meeting_date = meeting["date"]
    contract = meeting["contract"]
    probabilities = meeting["probabilities"]

    current_target = data["current_target"]

    print("")
    print(f"Próxima reunión: {meeting_date}")
    print(f"Contrato: {contract}")
    print(f"Tasa actual: {current_target}")
    print("")
    print("PROBABILIDADES:")

    alerts = []

    for rate, probability in probabilities.items():

        probability = float(probability)

        print(
            f"{rate}: {probability:.1f}%"
        )

        if probability >= THRESHOLD:

            # Determinar dirección
            if rate == current_target:
                direction = "⚪ MANTENER"

            else:
                try:
                    current_upper = float(
                        current_target.split("-")[1].replace("%", "")
                    )

                    target_upper = float(
                        rate.split("-")[1].replace("%", "")
                    )

                    if target_upper > current_upper:
                        direction = "🔴 ALZA"
                    else:
                        direction = "🟢 RECORTE"

                except Exception:
                    direction = "📊 CAMBIO"

            alerts.append(
                f"{direction}: {rate} → "
                f"{probability:.1f}%"
            )

    print("")

    if not alerts:

        print(
            f"ℹ️ Ninguna probabilidad supera "
            f"{THRESHOLD}%."
        )

        return

    message = (
        "CME FEDWATCH\n\n"
        f"Próxima reunión: {meeting_date}\n"
        f"Tasa actual: {current_target}\n\n"
        + "\n".join(alerts)
        + f"\n\nUmbral: {THRESHOLD}%"
    )

    print(message)

    send_ntfy(message)

    print("")
    print("✅ ALERTA ENVIADA AL IPHONE")


if __name__ == "__main__":
    main()