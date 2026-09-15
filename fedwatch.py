import os
import requests
from cme_fedwatch import get_probabilities

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
UMBRAL = 65.0


def alerta(titulo, mensaje):
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=mensaje.encode("utf-8"),
        headers={
            "Title": titulo,
            "Priority": "high",
            "Tags": "rotating_light"
        },
        timeout=15
    ).raise_for_status()


def main():

    data = get_probabilities("next")

    meeting = data["meetings"][0]

    fecha = meeting["date"]
    probabilidades = meeting["probabilities"]

    print(f"Próxima reunión: {fecha}")
    print(probabilidades)

    # Buscar la tasa actual
    current_target = data.get("current_target", "")

    # Convertir las probabilidades
    resultados = []

    for rango, prob in probabilidades.items():

        prob = float(prob)

        if prob >= UMBRAL:
            resultados.append(
                (rango, prob)
            )

    if not resultados:
        print("Ninguna probabilidad supera 65%.")
        return

    for rango, prob in resultados:

        titulo = "🚨 FEDWATCH > 65%"

        mensaje = (
            f"Próxima reunión FOMC: {fecha}\n\n"
            f"Resultado probable: {rango}\n"
            f"Probabilidad: {prob:.1f}%\n\n"
            f"Tasa actual: {current_target}\n\n"
            f"⚠️ Probabilidad superior al {UMBRAL:.0f}%."
        )

        alerta(titulo, mensaje)


if __name__ == "__main__":
    main()