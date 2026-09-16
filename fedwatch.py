#!/usr/bin/env python3

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURACIÓN
# ============================================================

CME_URL = "https://www.cmegroup.cn/fed-watch/"

THRESHOLD = 65.0
CHANGE_ALERT = 10.0

STATE_FILE = Path("fedwatch_state.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# ============================================================
# UTILIDADES
# ============================================================

def parse_pct(value):
    if value is None:
        return 0.0

    text = str(value)

    text = (
        text.replace("%", "")
        .replace("<", "")
        .replace(">", "")
        .replace("≈", "")
        .replace("\u200b", "")
        .strip()
    )

    match = re.search(r"(\d+(?:\.\d+)?)", text)

    if not match:
        return 0.0

    return float(match.group(1))


def parse_date(text):
    if not text:
        return ""

    text = text.strip()

    # Ejemplo:
    # 16 9月 2026
    match = re.search(
        r"(\d{1,2})\s*(\d{1,2})月\s*(\d{4})",
        text
    )

    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))

        return f"{year:04d}-{month:02d}-{day:02d}"

    # Ejemplo:
    # 16 Sep 2026
    match = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})",
        text
    )

    if match:
        day = int(match.group(1))
        month_text = match.group(2)
        year = int(match.group(3))

        try:
            month = datetime.strptime(
                month_text,
                "%b"
            ).month

            return f"{year:04d}-{month:02d}-{day:02d}"

        except ValueError:
            pass

    return text


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# EXTRACCIÓN DEL DOM DE QUIKSTRIKE
# ============================================================

def extract_meeting_from_dom(frame):

    javascript = r"""
    () => {

        function findInnerTable(keyword) {

            const tables =
                document.querySelectorAll("table.grid-thm");

            for (const table of tables) {

                const text =
                    Array.from(
                        table.querySelectorAll("th, td")
                    )
                    .map(el => el.textContent.trim())
                    .join(" ");

                if (text.includes(keyword)) {
                    return table;
                }
            }

            return null;
        }


        function parsePct(value) {

            if (!value) {
                return 0;
            }

            const cleaned =
                value
                    .toString()
                    .replace(/[%<>≈\u200b]/g, "")
                    .trim();

            const match =
                cleaned.match(/([\d.]+)/);

            return match
                ? parseFloat(match[1])
                : 0;
        }


        const result = {
            meeting_date: "",
            contract: "",
            expires: "",
            mid_price: "",
            current_target: "",
            summary: {},
            table: []
        };


        // ----------------------------------------------------
        // INFORMACIÓN DE LA REUNIÓN
        // ----------------------------------------------------

        const infoTable =
            findInnerTable("Meeting Date");

        if (infoTable) {

            const cells =
                infoTable.querySelectorAll("td");

            if (cells.length >= 4) {

                result.meeting_date =
                    cells[0].textContent.trim();

                result.contract =
                    cells[1].textContent.trim();

                result.expires =
                    cells[2].textContent.trim();

                result.mid_price =
                    cells[3].textContent.trim();
            }
        }


        // ----------------------------------------------------
        // RESUMEN:
        // EASE / NO CHANGE / HIKE
        // ----------------------------------------------------

        const probabilityTable =
            findInnerTable("Probabilities");

        if (probabilityTable) {

            const rows =
                probabilityTable.querySelectorAll("tr");

            for (const row of rows) {

                const cells =
                    row.querySelectorAll("td");

                if (cells.length >= 3) {

                    const values =
                        Array.from(cells)
                        .map(c => c.textContent.trim());

                    const percentages =
                        values
                        .map(parsePct)
                        .filter(v => v >= 0);

                    if (percentages.length >= 3) {

                        result.summary = {

                            ease: percentages[0],

                            no_change:
                                percentages[1],

                            hike:
                                percentages[2]
                        };

                        break;
                    }
                }
            }
        }


        // ----------------------------------------------------
        // TABLA DE TARGET RATES
        // ----------------------------------------------------

        const rateTable =
            findInnerTable("Target Rate (bps)");

        if (rateTable) {

            const rows =
                rateTable.querySelectorAll("tr");

            for (const row of rows) {

                if (row.classList.contains("hide")) {
                    continue;
                }

                const cells =
                    row.querySelectorAll("td");

                if (cells.length < 2) {
                    continue;
                }

                const range =
                    cells[0].textContent.trim();

                if (!/^\d+-\d+/.test(range)) {
                    continue;
                }

                const values =
                    Array.from(cells)
                    .slice(1)
                    .map(c => c.textContent.trim());

                result.table.push({

                    range: range,

                    now:
                        parsePct(values[0]),

                    day1:
                        parsePct(values[1]),

                    week1:
                        parsePct(values[2]),

                    month1:
                        parsePct(values[3])
                });
            }
        }


        // ----------------------------------------------------
        // TASA ACTUAL
        // ----------------------------------------------------

        const all =
            document.querySelectorAll("*");

        for (const element of all) {

            const match =
                element.textContent.match(
                    /Current target rate is (\d+-\d+)/i
                );

            if (match) {

                result.current_target =
                    match[1];

                break;
            }
        }


        return result;
    }
    """

    try:
        return frame.evaluate(javascript)
    except Exception:
        return None


# ============================================================
# TEXTO COMO RESPALDO
# ============================================================

def extract_from_text(text):

    result = {
        "meeting_date": "",
        "current_target": "",
        "summary": {},
        "table": []
    }

    # --------------------------------------------------------
    # FECHA
    # --------------------------------------------------------

    match = re.search(
        r"(\d{1,2}\s*\d{1,2}月\s*\d{4})",
        text
    )

    if match:
        result["meeting_date"] =
            parse_date(match.group(1))

    if not result["meeting_date"]:

        match = re.search(
            r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            text
        )

        if match:
            result["meeting_date"] =
                parse_date(match.group(1))


    # --------------------------------------------------------
    # CURRENT TARGET RATE
    # --------------------------------------------------------

    match = re.search(
        r"Current target rate is\s+(\d+-\d+)",
        text,
        re.IGNORECASE
    )

    if match:
        result["current_target"] =
            match.group(1)


    # --------------------------------------------------------
    # EASE / NO CHANGE / HIKE
    # --------------------------------------------------------

    lines = text.splitlines()

    for index, line in enumerate(lines):

        if re.search(
            r"EASE\s+NO\s*CHANGE\s+HIKE",
            line,
            re.IGNORECASE
        ):

            for next_line in lines[
                index + 1:index + 5
            ]:

                values = re.findall(
                    r"([\d.]+)\s*%",
                    next_line
                )

                if len(values) >= 3:

                    result["summary"] = {

                        "ease":
                            float(values[0]),

                        "no_change":
                            float(values[1]),

                        "hike":
                            float(values[2])
                    }

                    break

            break


    # --------------------------------------------------------
    # TARGET RATE TABLE
    # --------------------------------------------------------

    found_header = False

    for line in lines:

        stripped = line.strip()

        if (
            "TARGET RATE" in stripped.upper()
            and
            "PROBABILITY" in stripped.upper()
        ):

            found_header = True
            continue

        if not found_header:
            continue

        match = re.match(
            r"^(\d+-\d+.*?)\s+(.+)$",
            stripped
        )

        if not match:
            continue

        rate_range = match.group(1).strip()

        if not re.match(
            r"^\d+-\d+",
            rate_range
        ):
            continue

        percentages = re.findall(
            r"[\d.]+%",
            match.group(2)
        )

        if not percentages:
            continue

        result["table"].append({

            "range":
                rate_range,

            "now":
                parse_pct(percentages[0]),

            "day1":
                parse_pct(percentages[1])
                if len(percentages) > 1
                else 0,

            "week1":
                parse_pct(percentages[2])
                if len(percentages) > 2
                else 0,

            "month1":
                parse_pct(percentages[3])
                if len(percentages) > 3
                else 0
        })


    return result


# ============================================================
# SCRAPER PRINCIPAL
# ============================================================

def scrape_fedwatch():

    print()
    print("=" * 60)
    print("CME FEDWATCH — LIVE SCRAPER")
    print("=" * 60)
    print(f"Fuente: {CME_URL}")
    print()


    with sync_playwright() as playwright:

        print("Iniciando Chromium...")

        browser = playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--window-size=1920,1080"
            ]
        )

        context = browser.new_context(
            viewport={
                "width": 1920,
                "height": 1080
            },
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="America/Chicago"
        )

        page = context.new_page()

        print("Abriendo CME...")

        try:

            page.goto(
                CME_URL,
                wait_until="domcontentloaded",
                timeout=90000
            )

        except Exception as error:

            print(
                f"Advertencia al abrir CME: {error}"
            )

            # La página puede seguir cargando aunque
            # Playwright informe timeout.
            time.sleep(10)


        print("Esperando QuikStrike...")

        qs_frame = None

        # Hasta 120 segundos para que QuikStrike
        # cargue completamente.
        for elapsed in range(0, 121, 5):

            time.sleep(5)

            print(
                f"  Esperando... {elapsed + 5}s"
            )

            for frame in page.frames:

                try:

                    text =
                        frame.locator("body").inner_text(
                            timeout=3000
                        )

                    upper =
                        text.upper()

                    if (
                        "EASE" in upper
                        and
                        (
                            "HIKE" in upper
                            or
                            "NO CHANGE" in upper
                        )
                        and
                        len(text) > 500
                    ):

                        qs_frame = frame

                        print(
                            "✓ QuikStrike encontrado."
                        )

                        break

                except Exception:
                    continue

            if qs_frame:
                break


        if not qs_frame:

            print()
            print(
                "ERROR: CME cargó, pero "
                "QuikStrike no apareció."
            )

            # Intentamos guardar diagnóstico
            try:
                page.screenshot(
                    path="fedwatch_error.png",
                    full_page=True
                )
            except Exception:
                pass

            browser.close()

            raise RuntimeError(
                "QuikStrike no se pudo cargar."
            )


        # ----------------------------------------------------
        # ENCONTRAR REUNIONES
        # ----------------------------------------------------

        print("Buscando reuniones FOMC...")

        tabs = qs_frame.evaluate(
            """
            () => {

                const links =
                    document.querySelectorAll(
                        'a[id*="lbMeeting"]'
                    );

                return Array.from(links).map(
                    a => ({
                        id: a.id,
                        text: a.textContent.trim()
                    })
                );
            }
            """
        )

        if not tabs:

            browser.close()

            raise RuntimeError(
                "No se encontraron las reuniones FOMC."
            )


        print(
            f"✓ {len(tabs)} reuniones encontradas."
        )


        meetings = []


        # ----------------------------------------------------
        # LEER CADA REUNIÓN
        # ----------------------------------------------------

        previous_date = None

        for index, tab in enumerate(tabs):

            print(
                f"Reunión {index + 1}/{len(tabs)}: "
                f"{tab['text']}"
            )


            # Fecha anterior antes del click
            if index > 0:

                try:

                    previous_date =
                        qs_frame.evaluate(
                            """
                            () => {

                                const tables =
                                    document.querySelectorAll(
                                        "table.grid-thm"
                                    );

                                for (const table of tables) {

                                    const text =
                                        table.innerText;

                                    if (
                                        text.includes(
                                            "Meeting Date"
                                        )
                                    ) {

                                        const cells =
                                            table.querySelectorAll(
                                                "td"
                                            );

                                        return cells.length
                                            ? cells[0]
                                                .textContent
                                                .trim()
                                            : "";
                                    }
                                }

                                return "";
                            }
                            """
                        )

                except Exception:
                    previous_date = None


            # ------------------------------------------------
            # CLICK EN REUNIÓN
            # ------------------------------------------------

            clicked = qs_frame.evaluate(
                """
                (id) => {

                    const element =
                        document.getElementById(id);

                    if (!element) {
                        return false;
                    }

                    element.click();

                    return true;
                }
                """,
                tab["id"]
            )


            if not clicked:
                print("  No se pudo seleccionar.")
                continue


            # ------------------------------------------------
            # ESPERAR POSTBACK ASP.NET
            # ------------------------------------------------

            for _ in range(40):

                time.sleep(0.3)

                try:

                    ready =
                        qs_frame.evaluate(
                            """
                            (previousDate) => {

                                const loading =
                                    document.querySelector(
                                        ".throbber, [class*='loading']"
                                    );

                                if (
                                    loading &&
                                    loading.offsetParent !== null
                                ) {
                                    return false;
                                }

                                if (!previousDate) {
                                    return true;
                                }

                                const tables =
                                    document.querySelectorAll(
                                        "table.grid-thm"
                                    );

                                for (const table of tables) {

                                    if (
                                        table.innerText.includes(
                                            "Meeting Date"
                                        )
                                    ) {

                                        const cells =
                                            table.querySelectorAll(
                                                "td"
                                            );

                                        const current =
                                            cells.length
                                                ? cells[0]
                                                    .textContent
                                                    .trim()
                                                : "";

                                        return (
                                            current &&
                                            current !== previousDate
                                        );
                                    }
                                }

                                return false;
                            }
                            """,
                            previous_date
                        )

                    if ready:
                        break

                except Exception:
                    pass


            time.sleep(0.5)


            # ------------------------------------------------
            # EXTRAER DATOS
            # ------------------------------------------------

            data =
                extract_meeting_from_dom(
                    qs_frame
                )


            if not data or not data.get("table"):

                print(
                    "  DOM vacío. Usando respaldo de texto..."
                )

                try:

                    text =
                        qs_frame.locator(
                            "body"
                        ).inner_text(
                            timeout=5000
                        )

                    data =
                        extract_from_text(text)

                except Exception:

                    data = None


            if not data:
                print("  ERROR leyendo reunión.")
                continue


            meeting_date =
                parse_date(
                    data.get(
                        "meeting_date",
                        ""
                    )
                )


            summary =
                data.get(
                    "summary",
                    {}
                )


            print(
                f"  Fecha: {meeting_date}"
            )

            print(
                f"  ALZA: "
                f"{summary.get('hike', 0)}%"
            )

            print(
                f"  MANTENER: "
                f"{summary.get('no_change', 0)}%"
            )

            print(
                f"  RECORTE: "
                f"{summary.get('ease', 0)}%"
            )


            meetings.append({

                "meeting_date":
                    meeting_date,

                "summary":
                    summary,

                "table":
                    data.get(
                        "table",
                        []
                    ),

                "current_target":
                    data.get(
                        "current_target",
                        ""
                    )
            })


        browser.close()


    if not meetings:

        raise RuntimeError(
            "CME no devolvió ninguna reunión."
        )


    return meetings


# ============================================================
# ENCONTRAR PRÓXIMA REUNIÓN
# ============================================================

def get_next_meeting(meetings):

    today =
        datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d")


    valid = []

    for meeting in meetings:

        date =
            meeting.get(
                "meeting_date",
                ""
            )

        if re.match(
            r"^\d{4}-\d{2}-\d{2}$",
            date
        ):

            if date >= today:

                valid.append(meeting)


    if not valid:
        return None


    valid.sort(
        key=lambda x:
            x["meeting_date"]
    )


    return valid[0]


# ============================================================
# DETERMINAR SEÑAL
# ============================================================

def determine_signal(summary):

    hike =
        float(
            summary.get(
                "hike",
                0
            )
        )

    ease =
        float(
            summary.get(
                "ease",
                0
            )
        )

    hold =
        float(
            summary.get(
                "no_change",
                0
            )
        )


    values = {

        "ALZA":
            hike,

        "RECORTE":
            ease,

        "MANTENER":
            hold
    }


    direction =
        max(
            values,
            key=values.get
        )

    probability =
        values[direction]


    return direction, probability, values


# ============================================================
# DECIDIR SI HAY QUE ENVIAR ALERTA
# ============================================================

def should_alert(
    state,
    meeting_date,
    direction,
    probability
):

    if probability < THRESHOLD:

        return False, "Por debajo de 65%"


    previous_meeting =
        state.get(
            "meeting_date"
        )

    previous_direction =
        state.get(
            "direction"
        )

    previous_probability =
        state.get(
            "probability"
        )


    # Primera señal
    if previous_meeting is None:

        return True, "Primera señal >=65%"


    # Cambió la reunión
    if previous_meeting != meeting_date:

        return True, "Nueva reunión FOMC"


    # Cambió la dirección
    if (
        previous_direction
        and
        previous_direction != direction
    ):

        return True, "Cambio de dirección"


    # Cambio >= 10 puntos
    if previous_probability is not None:

        difference =
            abs(
                probability
                -
                float(previous_probability)
            )

        if difference >= CHANGE_ALERT:

            return True, (
                f"Cambio de "
                f"{difference:.1f} puntos"
            )


    return False, "Sin cambio suficiente"


# ============================================================
# NTFY
# ============================================================

def send_ntfy(
    direction,
    probability,
    meeting_date,
    values,
    reason
):

    if not NTFY_TOPIC:

        print(
            "ERROR: falta el secreto NTFY_TOPIC."
        )

        return False


    emoji = {

        "ALZA": "🔴",

        "RECORTE": "🟢",

        "MANTENER": "⚪"
    }.get(
        direction,
        "⚪"
    )


    title =
        f"{emoji} CME FedWatch — {direction}"


    message = (
        f"{direction}: {probability:.1f}%\n"
        f"Reunión: {meeting_date}\n\n"
        f"🔴 ALZA: {values['ALZA']:.1f}%\n"
        f"🟢 RECORTE: {values['RECORTE']:.1f}%\n"
        f"⚪ MANTENER: {values['MANTENER']:.1f}%\n\n"
        f"Motivo: {reason}\n"
        f"Fuente: CME FedWatch / QuikStrike"
    )


    try:

        response =
            requests.post(

                f"https://ntfy.sh/{NTFY_TOPIC}",

                data=message.encode(
                    "utf-8"
                ),

                headers={
                    "Title": title,
                    "Priority": "high",
                    "Tags": "chart_with_upwards_trend"
                },

                timeout=20
            )


        if response.status_code >= 200 and response.status_code < 300:

            print(
                "✓ Notificación enviada a ntfy."
            )

            return True


        print(
            f"ERROR ntfy: "
            f"{response.status_code}"
        )

        print(
            response.text
        )

        return False


    except Exception as error:

        print(
            f"ERROR enviando ntfy: {error}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "============================================================"
    )
    print(
        "CME FEDWATCH MONITOR"
    )
    print(
        "============================================================"
    )

    print(
        f"Umbral: {THRESHOLD}%"
    )

    print(
        f"Cambio para alerta: {CHANGE_ALERT} puntos"
    )

    print(
        f"Hora UTC: "
        f"{datetime.now(timezone.utc).isoformat()}"
    )


    # --------------------------------------------------------
    # SCRAPE
    # --------------------------------------------------------

    meetings =
        scrape_fedwatch()


    # --------------------------------------------------------
    # PRÓXIMA REUNIÓN
    # --------------------------------------------------------

    next_meeting =
        get_next_meeting(
            meetings
        )


    if not next_meeting:

        raise RuntimeError(
            "No se encontró la próxima reunión FOMC."
        )


    meeting_date =
        next_meeting[
            "meeting_date"
        ]

    summary =
        next_meeting[
            "summary"
        ]


    # --------------------------------------------------------
    # SEÑAL
    # --------------------------------------------------------

    direction, probability, values =
        determine_signal(
            summary
        )


    print()
    print(
        "============================================================"
    )

    print(
        f"PRÓXIMA REUNIÓN: {meeting_date}"
    )

    print(
        f"🔴 ALZA: {values['ALZA']:.1f}%"
    )

    print(
        f"🟢 RECORTE: {values['RECORTE']:.1f}%"
    )

    print(
        f"⚪ MANTENER: {values['MANTENER']:.1f}%"
    )

    print(
        f"SEÑAL PRINCIPAL: {direction} "
        f"{probability:.1f}%"
    )

    print(
        "============================================================"
    )


    # --------------------------------------------------------
    # ESTADO ANTERIOR
    # --------------------------------------------------------

    state =
        load_state()


    alert, reason =
        should_alert(
            state,
            meeting_date,
            direction,
            probability
        )


    print(
        f"Alerta: {'SÍ' if alert else 'NO'}"
    )

    print(
        f"Motivo: {reason}"
    )


    # --------------------------------------------------------
    # ENVIAR ALERTA
    # --------------------------------------------------------

    if alert:

        send_ntfy(
            direction,
            probability,
            meeting_date,
            values,
            reason
        )


        # Guardamos solamente el último estado
        # que produjo una alerta.
        #
        # Así NO se generan notificaciones cada
        # 15 minutos mientras el dato permanezca igual.

        state = {

            "meeting_date":
                meeting_date,

            "direction":
                direction,

            "probability":
                probability,

            "updated_at":
                datetime.now(
                    timezone.utc
                ).isoformat()
        }


        save_state(
            state
        )

        print(
            "✓ Estado actualizado."
        )


    else:

        print(
            "No se envía notificación."
        )


    print()
    print(
        "Proceso terminado correctamente."
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print(
            "============================================================"
        )

        print(
            "ERROR"
        )

        print(
            str(error)
        )

        print(
            "============================================================"
        )

        sys.exit(1)