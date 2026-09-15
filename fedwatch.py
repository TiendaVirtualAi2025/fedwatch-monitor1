import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
THRESHOLD = 65.0

CME_URLS = [
    "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    "https://www.cmegroup.cn/fed-watch/",
]


def parse_pct(text):
    if not text:
        return 0.0

    text = str(text)
    match = re.search(r"([\d.]+)", text)

    return float(match.group(1)) if match else 0.0


def send_ntfy(message):
    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    response = requests.post(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": "🚨 FEDWATCH > 65%",
            "Priority": "high",
            "Tags": "warning,chart_with_upwards_trend",
        },
        timeout=20,
    )

    response.raise_for_status()


def extract_fedwatch(frame):

    data = frame.evaluate("""
    () => {

        function pct(text) {
            if (!text) return 0;
            const m = text.replace(/[%<>≈]/g, '').match(/[0-9.]+/);
            return m ? parseFloat(m[0]) : 0;
        }

        const result = {
            meeting_date: "",
            contract: "",
            current_target: "",
            summary: {
                ease: 0,
                no_change: 0,
                hike: 0
            }
        };

        const tables = document.querySelectorAll("table.grid-thm");

        for (const table of tables) {

            const text = table.innerText || "";

            /*
             * Meeting information
             */
            if (text.includes("Meeting Date")) {

                const cells = table.querySelectorAll("td");

                if (cells.length >= 4) {
                    result.meeting_date = cells[0].innerText.trim();
                    result.contract = cells[1].innerText.trim();
                }
            }

            /*
             * Probability summary
             */
            if (text.includes("Probabilities")) {

                const rows = table.querySelectorAll("tr");

                for (const row of rows) {

                    const cells = row.querySelectorAll("td");

                    if (cells.length >= 3) {

                        result.summary = {
                            ease: pct(cells[0].innerText),
                            no_change: pct(cells[1].innerText),
                            hike: pct(cells[2].innerText)
                        };
                    }
                }
            }
        }

        /*
         * Current target rate
         */
        const allText = document.body.innerText;

        const target = allText.match(
            /Current target rate is\\s*([0-9]+-[0-9]+)/
        );

        if (target) {
            result.current_target = target[1];
        }

        return result;
    }
    """)

    return data


def main():

    print("======================================")
    print(" CME FEDWATCH MONITOR")
    print("======================================")

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

        for url in CME_URLS:

            print(f"Abriendo: {url}")

            try:

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                for seconds in range(0, 91, 5):

                    time.sleep(5)

                    print(
                        f"Esperando FedWatch... {seconds + 5}s"
                    )

                    for frame in page.frames:

                        try:

                            text = frame.inner_text("body")

                            if (
                                "EASE" in text.upper()
                                and len(text) > 500
                            ):
                                fedwatch_frame = frame
                                break

                        except Exception:
                            pass

                    if fedwatch_frame:
                        break

                if fedwatch_frame:
                    print("✅ FedWatch encontrado.")
                    break

            except Exception as e:

                print(
                    f"No se pudo cargar {url}: {e}"
                )

        if not fedwatch_frame:

            browser.close()

            raise RuntimeError(
                "No se pudo cargar el widget FedWatch de CME."
            )

        data = extract_fedwatch(fedwatch_frame)

        print("")
        print("RESULTADO:")
        print(data)

        meeting = data["meeting_date"]

        if not meeting:
            browser.close()
            raise RuntimeError(
                "FedWatch cargó, pero no encontramos la reunión."
            )

        summary = data["summary"]

        print("")
        print(f"Reunión: {meeting}")
        print(f"Recorte: {summary['ease']}%")
        print(f"Mantener: {summary['no_change']}%")
        print(f"Alza: {summary['hike']}%")

        alerts = []

        if summary["ease"] >= THRESHOLD:
            alerts.append(
                f"🟢 RECORTE: {summary['ease']:.1f}%"
            )

        if summary["no_change"] >= THRESHOLD:
            alerts.append(
                f"⚪ MANTENER: {summary['no_change']:.1f}%"
            )

        if summary["hike"] >= THRESHOLD:
            alerts.append(
                f"🔴 ALZA: {summary['hike']:.1f}%"
            )

        if alerts:

            message = (
                "CME FEDWATCH\n\n"
                f"Próxima reunión: {meeting}\n\n"
                + "\n".join(alerts)
                + "\n\n"
                f"Umbral: {THRESHOLD}%"
            )

            print("")
            print(message)

            send_ntfy(message)

            print("")
            print("✅ ALERTA ENVIADA AL IPHONE")

        else:

            print("")
            print(
                f"Sin probabilidades >= {THRESHOLD}%."
            )

        browser.close()


if __name__ == "__main__":
    main()