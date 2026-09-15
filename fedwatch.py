import os
import requests

NTFY_TOPIC = os.environ["NTFY_TOPIC"]

UMBRAL_ALERTA = 65.0


def enviar_alerta(titulo, mensaje):
    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    headers = {
        "Title": titulo,
        "Priority": "high",
        "Tags": "rotating_light"
    }

    response = requests.post(
        url,
        data=mensaje.encode("utf-8"),
        headers=headers,
        timeout=15
    )

    response.raise_for_status()


def consultar_fedwatch():
    url = "https://www.cmegroup.com/CmeApp/mvc/FedWatch/getMeetings"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=15
    )

    response.raise_for_status()

    return response.json()


def main():

    data = consultar_fedwatch()

    meetings = data.get("meetings", [])

    if not meetings:
        print("No se encontraron reuniones.")
        return

    meeting = meetings[0]

    fecha = meeting.get(
        "meetingDate",
        "Próxima reunión"
    )

    recorte = float(
        meeting.get("easeProbability", 0)
    )

    mantener = float(
        meeting.get("unchangedProbability", 0)
    )

    alza = float(
        meeting.get("hikeProbability", 0)
    )

    print(
        f"[{fecha}] "
        f"Recorte: {recorte}% | "
        f"Mantener: {mantener}% | "
        f"Alza: {alza}%"
    )

    if recorte >= UMBRAL_ALERTA:

        titulo = "🚨 FEDWATCH — RECORTE"

        mensaje = (
            f"Próxima reunión FOMC: {fecha}\n\n"
            f"🟢 Recorte: {recorte:.1f}%\n"
            f"⚪ Mantener: {mantener:.1f}%\n"
            f"🔴 Alza: {alza:.1f}%\n\n"
            f"⚠️ Probabilidad de RECORTE supera "
            f"el {UMBRAL_ALERTA:.0f}%."
        )

        enviar_alerta(titulo, mensaje)

    elif mantener >= UMBRAL_ALERTA:

        titulo = "ℹ️ FEDWATCH — MANTENER"

        mensaje = (
            f"Próxima reunión FOMC: {fecha}\n\n"
            f"🟢 Recorte: {recorte:.1f}%\n"
            f"⚪ Mantener: {mantener:.1f}%\n"
            f"🔴 Alza: {alza:.1f}%\n\n"
            f"Probabilidad de MANTENER supera "
            f"el {UMBRAL_ALERTA:.0f}%."
        )

        enviar_alerta(titulo, mensaje)

    elif alza >= UMBRAL_ALERTA:

        titulo = "🚨 FEDWATCH — ALZA"

        mensaje = (
            f"Próxima reunión FOMC: {fecha}\n\n"
            f"🟢 Recorte: {recorte:.1f}%\n"
            f"⚪ Mantener: {mantener:.1f}%\n"
            f"🔴 Alza: {alza:.1f}%\n\n"
            f"⚠️ Probabilidad de ALZA supera "
            f"el {UMBRAL_ALERTA:.0f}%."
        )

        enviar_alerta(titulo, mensaje)


if __name__ == "__main__":
    main()
