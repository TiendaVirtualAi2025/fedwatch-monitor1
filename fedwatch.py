import os
import re
import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
UMBRAL = 65.0

URL = "https://www.frenzycap.com/fedwatch"


def enviar_alerta(titulo, mensaje):
    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    response = requests.post(
        url,
        data=mensaje.encode("utf-8"),
        headers={
            "Title": titulo,
            "Priority": "high",
            "Tags": "rotating_light"
        },
        timeout=15
    )

    response.raise_for_status()


def obtener_fedwatch():

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140 Safari/537.36"
        )
    }

    r = requests.get(URL, headers=headers, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    texto = soup.get_text(" ", strip=True)

    # Buscar la primera reunión FOMC
    patron = re.search(
        r"(Sep|Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug)"
        r"\s+\d{1,2},\s+2026",
        texto
    )

    if not patron:
        raise Exception("No se encontró la próxima reunión FOMC.")

    fecha = patron.group(0)

    # Buscar porcentajes posteriores a la fecha.
    resto = texto[patron.end():patron.end() + 1200]

    porcentajes = [
        float(x)
        for x in re.findall(r"(\d+(?:\.\d+)?)%", resto)
    ]

    if len(porcentajes) < 2:
        raise Exception(
            f"No se pudieron encontrar probabilidades. "
            f"Datos encontrados: {porcentajes}"
        )

    return fecha, porcentajes


def main():

    fecha, porcentajes = obtener_fedwatch()

    print("===================================")
    print("FEDWATCH MONITOR")
    print("===================================")
    print(f"Reunión: {fecha}")
    print(f"Probabilidades encontradas: {porcentajes}")

    # Para la próxima reunión normalmente tendremos:
    # HOLD + HIKE o HOLD + CUT.
    #
    # Determinamos el escenario dominante.
    mayor = max(porcentajes[:5])

    if mayor < UMBRAL:
        print(
            f"Ninguna probabilidad supera {UMBRAL}%."
        )
        return

    # En el escenario actual, el movimiento alcista
    # aparece después de la probabilidad de mantener.
    if len(porcentajes) >= 2:

        p1 = porcentajes[0]
        p2 = porcentajes[1]

        if p2 >= UMBRAL:

            titulo = "🚨 FEDWATCH — ALZA > 65%"

            mensaje = (
                f"Próxima reunión FOMC: {fecha}\n\n"
                f"⚪ Mantener: {p1:.1f}%\n"
                f"🔴 Alza: {p2:.1f}%\n\n"
                f"🚨 Probabilidad de ALZA supera "
                f"{UMBRAL:.0f}%.\n\n"
                f"Confirmar con:\n"
                f"• Treasury 10Y\n"
                f"• USD\n"
                f"• CPI / PCE / NFP\n"
                f"• Discurso de la Fed"
            )

            enviar_alerta(titulo, mensaje)

        elif p1 >= UMBRAL:

            titulo = "ℹ️ FEDWATCH — MANTENER > 65%"

            mensaje = (
                f"Próxima reunión FOMC: {fecha}\n\n"
                f"⚪ Mantener: {p1:.1f}%\n"
                f"🔴 Alza: {p2:.1f}%\n\n"
                f"Probabilidad de MANTENER supera "
                f"{UMBRAL:.0f}%."
            )

            enviar_alerta(titulo, mensaje)

    print("Monitor terminado correctamente.")


if __name__ == "__main__":
    main()