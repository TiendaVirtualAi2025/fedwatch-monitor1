import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
THRESHOLD = 65.0

URLS = [
    "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    "https://www.cmegroup.cn/fed-watch/",
]


def parse_date(text):
    text = text.strip()

    m = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})",
        text
    )

    if m:
        months = {
            "Jan": "01", "Feb": "02", "Mar": "03",
            "Apr": "04", "May": "05", "Jun": "06",
            "Jul": "07", "Aug": "08", "Sep": "09",
            "Oct": "10", "Nov": "11", "Dec": "12"
        }

        return (
            f"{m.group(3)}-"
            f"{months[m.group(2)]}-"
            f"{int(m.group(1)):02d}"
        )

    return text


def parse_probabilities(text):

    lines = text.splitlines()

    ease = 0.0
    no_change = 0.0
    hike = 0.0

    for i, line in enumerate(lines):

        clean = re.sub(r"\s+", " ", line.strip()).upper()

        if (
            "EASE" in clean
            and "NO CHANGE" in clean
            and "HIKE" in clean
        ):

            # Buscar porcentajes en las siguientes líneas
            for j in range(i, min(i + 5, len(lines))):

                values = re.findall(
                    r"(\d+(?:\.\d+)?)\s*%",
                    lines[j]
                )

                if len(values) >= 3:

                    ease = float(values[0])
                    no_change = float(values[1])
                    hike = float(values[2])

                    return {
                        "ease": ease,
                        "no_change": no_change,
                        "hike": hike
                    }

    return {
        "ease": ease,
        "no_change": no_change,
        "hike": hike
    }


def extract_meeting(text):

    # Ejemplo:
    # 16 Sep 2026 ZQU6 30 Sep 2026 96.1400

    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+"
        r"([A-Z0-9]+)\s+"
        r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+"
        r"([\d.]+)",
        text
    )

    if not match:
        return None

    return {
        "date": parse_date(match.group(1)),
        "contract": match.group(2),
        "expiry": parse_date(match.group(3)),
        "price": match.group(4)
    }


def send_notification(message):

    response = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "CME FedWatch > 65%",
            "Priority": "high",
            "Tags": "warning"
        },
        timeout=20
    )

    response.raise_for_status()

    print("✅ NTFY ENVIADO")


def main():

    print("=" * 50)
    print("CME FEDWATCH MONITOR")
    print("=" * 50)

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        page = browser.new_page(
            viewport={
                "width": 1920,
                "height": 1080
            },
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )

        fedwatch_frame = None

        for url in URLS:

            print(f"\nAbriendo: {url}")

            try:

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                for seconds in range(5, 91, 5):

                    time.sleep(5)

                    print(
                        f"Esperando FedWatch... {seconds}s"
                    )

                    for frame in page.frames:

                        try:

                            text = frame.inner_text("body")

                            if (
                                "EASE" in text.upper()
                                and len(text) > 500
                            ):
                                fedwatch_frame = frame

                                print(
                                    "✅ Widget FedWatch encontrado"
                                )

                                break

                        except Exception:
                            pass

                    if fedwatch_frame:
                        break

                if fedwatch_frame:
                    break

            except Exception as e:

                print(f"Error cargando página: {e}")

        if not fedwatch_frame:

            browser.close()

            raise RuntimeError(
                "CME FedWatch no pudo cargar."
            )

        # -------------------------------------------------
        # BUSCAR LAS REUNIONES
        # -------------------------------------------------

        tabs = fedwatch_frame.evaluate("""
        () => {

            const links =
                document.querySelectorAll(
                    'a[id*="lbMeeting"]'
                );

            return Array.from(links).map(a => ({
                id: a.id,
                text: a.textContent.trim()
            }));

        }
        """)

        print(
            f"Reuniones encontradas: {len(tabs)}"
        )

        if not tabs:

            browser.close()

            raise RuntimeError(
                "CME cargó, pero no aparecen las reuniones."
            )

        # Primera reunión = próxima reunión
        first_tab = tabs[0]

        print(
            f"Próxima reunión detectada: "
            f"{first_tab['text']}"
        )

        # -------------------------------------------------
        # EXTRAER DATOS DE LA REUNIÓN ACTUAL
        # -------------------------------------------------

        text = fedwatch_frame.inner_text("body")

        meeting = extract_meeting(text)
        probabilities = parse_probabilities(text)

        # Si el texto inicial no contiene la reunión,
        # pulsamos la primera pestaña.

        if not meeting:

            print("Pulsando primera reunión...")

            fedwatch_frame.evaluate(
                """
                id => {
                    const el =
                        document.getElementById(id);

                    if (el) {
                        el.click();
                        return true;
                    }

                    return false;
                }
                """,
                first_tab["id"]
            )

            time.sleep(3)

            text = fedwatch_frame.inner_text("body")

            meeting = extract_meeting(text)
            probabilities = parse_probabilities(text)

        if not meeting:

            browser.close()

            raise RuntimeError(
                "Encontré FedWatch pero no pude extraer "
                "la fecha de la reunión."
            )

        # -------------------------------------------------
        # MOSTRAR RESULTADO
        # -------------------------------------------------

        print("")
        print("RESULTADO CME FEDWATCH")
        print("-" * 40)

        print(
            f"Reunión: {meeting['date']}"
        )

        print(
            f"Contrato: {meeting['contract']}"
        )

        print(
            f"RECORTE: {probabilities['ease']:.1f}%"
        )

        print(
            f"MANTENER: "
            f"{probabilities['no_change']:.1f}%"
        )

        print(
            f"ALZA: {probabilities['hike']:.1f}%"
        )

        # -------------------------------------------------
        # ALERTAS
        # -------------------------------------------------

        alerts = []

        if probabilities["ease"] >= THRESHOLD:

            alerts.append(
                f"🟢 RECORTE: "
                f"{probabilities['ease']:.1f}%"
            )

        if probabilities["no_change"] >= THRESHOLD:

            alerts.append(
                f"⚪ MANTENER: "
                f"{probabilities['no_change']:.1f}%"
            )

        if probabilities["hike"] >= THRESHOLD:

            alerts.append(
                f"🔴 ALZA: "
                f"{probabilities['hike']:.1f}%"
            )

        if alerts:

            message = (
                "CME FEDWATCH\n\n"
                f"Próxima reunión: {meeting['date']}\n"
                f"Contrato: {meeting['contract']}\n\n"
                + "\n".join(alerts)
                + f"\n\nUmbral: {THRESHOLD}%"
            )

            print("")
            print(message)

            send_notification(message)

        else:

            print("")
            print(
                f"ℹ️ Ninguna probabilidad supera "
                f"{THRESHOLD}%."
            )

        browser.close()


if __name__ == "__main__":
    main()