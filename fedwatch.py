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

    # Ejemplo: 16 9月 2026
    match = re.search(
        r"(\d{1,2})\s*(\d{1,2})月\s*(\d{4})",
        text
    )

    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))

        return f"{year:04d}-{month:02d}-{day:02d}"

    # Ejemplo: 16 Sep 2026
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
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return {}


def save_state(state):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# EXTRACCIÓN DEL DOM
# ============================================================

def extract_meeting_from_dom(frame):

    javascript = r"""
    () => {

        function findTable(keyword) {

            const tables =
                document.querySelectorAll("table");

            for (const table of tables) {

                const text =
                    table.innerText || "";

                if (
                    text.toLowerCase()
                    .includes(keyword.toLowerCase())
                ) {
                    return table;
                }
            }

            return null;
        }


        function pct(value) {

            if (!value) {
                return 0;
            }

            const match =
                value
                    .toString()
                    .replace(/,/g, "")
                    .match(/([\d.]+)\s*%?/);

            if (!match) {
                return 0;
            }

            return parseFloat(match[1]);
        }


        const result = {

            meeting_date: "",

            current_target: "",

            summary: {

                ease: 0,

                no_change: 0,

                hike: 0
            },

            table: []
        };


        // ====================================================
        // TEXTO COMPLETO
        // ====================================================

        const bodyText =
            document.body
                ? document.body.innerText
                : "";


        // ====================================================
        // FECHA DE REUNIÓN
        // ====================================================

        let match =
            bodyText.match(
                /Meeting Date[\s\S]{0,150}?(\d{1,2}[\s,\/-]+\w+[\s,\/-]+\d{4})/i
            );

        if (match) {

            result.meeting_date =
                match[1].trim();
        }


        // Formato chino
        if (!result.meeting_date) {

            match =
                bodyText.match(
                    /(\d{1,2}\s*\d{1,2}月\s*\d{4})/
                );

            if (match) {

                result.meeting_date =
                    match[1].trim();
            }
        }


        // ====================================================
        // CURRENT TARGET
        // ====================================================

        match =
            bodyText.match(
                /Current target rate is\s+(\d+-\d+)/i
            );

        if (match) {

            result.current_target =
                match[1];
        }


        // ====================================================
        // BUSCAR PROBABILIDADES
        // ====================================================

        const tables =
            document.querySelectorAll("table");


        for (const table of tables) {

            const text =
                table.innerText || "";

            const upper =
                text.toUpperCase();


            if (
                upper.includes("EASE") &&
                upper.includes("NO CHANGE") &&
                upper.includes("HIKE")
            ) {

                const percentages =
                    text.match(
                        /\d+(?:\.\d+)?\s*%/g
                    ) || [];


                if (percentages.length >= 3) {

                    const values =
                        percentages.map(pct);


                    result.summary.ease =
                        values[0];

                    result.summary.no_change =
                        values[1];

                    result.summary.hike =
                        values[2];
                }
            }
        }


        // ====================================================
        // TARGET RATE TABLE
        // ====================================================

        for (const table of tables) {

            const rows =
                table.querySelectorAll("tr");


            for (const row of rows) {

                const cells =
                    row.querySelectorAll("td");


                if (cells.length < 2) {
                    continue;
                }


                const values =
                    Array.from(cells)
                        .map(
                            cell =>
                                cell.innerText.trim()
                        );


                const range =
                    values[0];


                if (
                    !/^\d+-\d+/.test(range)
                ) {
                    continue;
                }


                const percentages =
                    values
                        .slice(1)
                        .map(pct);


                if (!percentages.length) {
                    continue;
                }


                result.table.push({

                    range: range,

                    now:
                        percentages[0] || 0,

                    day1:
                        percentages[1] || 0,

                    week1:
                        percentages[2] || 0,

                    month1:
                        percentages[3] || 0
                });
            }
        }


        return result;
    }
    """

    try:

        return frame.evaluate(
            javascript
        )

    except Exception as error:

        print(
            f"Error extrayendo DOM: {error}"
        )

        return None


# ============================================================
# RESPALDO: EXTRAER DESDE TEXTO
# ============================================================

def extract_from_text(text):

    result = {

        "meeting_date": "",

        "current_target": "",

        "summary": {

            "ease": 0,

            "no_change": 0,

            "hike": 0
        },

        "table": []
    }


    # ========================================================
    # FECHA
    # ========================================================

    match = re.search(
        r"(\d{1,2}\s*\d{1,2}月\s*\d{4})",
        text
    )

    if match:

        result["meeting_date"] = parse_date(
            match.group(1)
        )


    if not result["meeting_date"]:

        match = re.search(
            r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            text
        )

        if match:

            result["meeting_date"] = parse_date(
                match.group(1)
            )


    # ========================================================
    # CURRENT TARGET
    # ========================================================

    match = re.search(
        r"Current target rate is\s+(\d+-\d+)",
        text,
        re.IGNORECASE
    )

    if match:

        result["current_target"] = match.group(1)


    # ========================================================
    # PROBABILIDADES
    # ========================================================

    lines = text.splitlines()


    for index, line in enumerate(lines):

        if re.search(
            r"EASE\s+NO\s*CHANGE\s+HIKE",
            line,
            re.IGNORECASE
        ):

            for next_line in lines[
                index + 1:index + 6
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


    return result


# ============================================================
# SCRAPER CME
# ============================================================

def scrape_fedwatch():

    print()
    print("=" * 60)
    print("CME FEDWATCH — LIVE SCRAPER")
    print("=" * 60)
    print(
        f"Fuente: {CME_URL}"
    )
    print()


    with sync_playwright() as playwright:

        print(
            "Iniciando Chromium..."
        )


        browser =
            playwright.chromium.launch(
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


        context =
            browser.new_context(
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=USER_AGENT,
                locale="en-US"
            )


        page =
            context.new_page()


        print(
            "Abriendo CME..."
        )


        try:

            page.goto(
                CME_URL,
                wait_until="domcontentloaded",
                timeout=90000
            )

        except Exception as error:

            print(
                f"Advertencia de navegación: {error}"
            )

            print(
                "La página puede seguir cargando..."
            )


        print(
            "Esperando QuikStrike..."
        )


        qs_frame = None


        # ====================================================
        # BUSCAR FRAME
        # ====================================================

        for elapsed in range(
            0,
            121,
            5
        ):

            time.sleep(5)


            print(
                f"Esperando... {elapsed + 5}s"
            )


            for frame in page.frames:

                try:

                    text =
                        frame.locator(
                            "body"
                        ).inner_text(
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
                        len(text) > 300
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


        # ====================================================
        # FALLBACK: PÁGINA PRINCIPAL
        # ====================================================

        if not qs_frame:

            try:

                text =
                    page.locator(
                        "body"
                    ).inner_text(
                        timeout=5000
                    )


                if (
                    "EASE" in text.upper()
                    and
                    "HIKE" in text.upper()
                ):

                    qs_frame = page

                    print(
                        "✓ FedWatch encontrado "
                        "en la página principal."
                    )

            except Exception:
                pass


        if not qs_frame:

            try:

                page.screenshot(
                    path="fedwatch_error.png",
                    full_page=True
                )

                print(
                    "Se guardó fedwatch_error.png"
                )

            except Exception:
                pass


            browser.close()


            raise RuntimeError(
                "QuikStrike/FedWatch no apareció."
            )


        # ====================================================
        # EXTRAER INFORMACIÓN
        # ====================================================

        print(
            "Extrayendo información..."
        )


        data =
            extract_meeting_from_dom(
                qs_frame
            )


        if not data:

            try:

                text =
                    qs_frame.locator(
                        "body"
                    ).inner_text(
                        timeout=5000
                    )


                data =
                    extract_from_text(
                        text
                    )

            except Exception:

                data = None


        browser.close()


        if not data:

            raise RuntimeError(
                "No fue posible extraer "
                "datos de CME."
            )


        return data


# ============================================================
# ENCONTRAR PROBABILIDADES REALES
# ============================================================

def determine_signal(data):

    summary =
        data.get(
            "summary",
            {}
        )


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

        "ALZA": hike,

        "RECORTE": ease,

        "MANTENER": hold
    }


    direction =
        max(
            values,
            key=values.get
        )


    probability =
        values[direction]


    return (
        direction,
        probability,
        values
    )


# ============================================================
# ALERTAS
# ============================================================

def should_alert(
    state,
    meeting_date,
    direction,
    probability
):

    if probability < THRESHOLD:

        return (
            False,
            "Por debajo de 65%"
        )


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


    if previous_meeting is None:

        return (
            True,
            "Primera señal >=65%"
        )


    if previous_meeting != meeting_date:

        return (
            True,
            "Nueva reunión FOMC"
        )


    if (
        previous_direction
        and
        previous_direction != direction
    ):

        return (
            True,
            "Cambio de dirección"
        )


    if previous_probability is not None:

        difference =
            abs(
                probability -
                float(previous_probability)
            )


        if difference >= CHANGE_ALERT:

            return (
                True,
                f"Cambio de {difference:.1f} puntos"
            )


    return (
        False,
        "Sin cambio suficiente"
    )


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
            "ERROR: falta NTFY_TOPIC."
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


        if 200 <= response.status_code < 300:

            print(
                "✓ Notificación enviada."
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
            f"ERROR ntfy: {error}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("CME FEDWATCH MONITOR")
    print("=" * 60)

    print(
        f"Umbral: {THRESHOLD}%"
    )

    print(
        f"Cambio para alerta: "
        f"{CHANGE_ALERT} puntos"
    )

    print(
        "Hora UTC: "
        f"{datetime.now(timezone.utc).isoformat()}"
    )


    # ========================================================
    # SCRAPE
    # ========================================================

    data =
        scrape_fedwatch()


    # ========================================================
    # FECHA
    # ========================================================

    meeting_date =
        parse_date(
            data.get(
                "meeting_date",
                ""
            )
        )


    if not meeting_date:

        # Si CME no entrega fecha en el primer
        # campo, intentamos buscarla nuevamente
        # dentro del texto.

        meeting_date =
            data.get(
                "meeting_date",
                ""
            )


    if not meeting_date:

        raise RuntimeError(
            "CME no entregó la fecha "
            "de la reunión."
        )


    # ========================================================
    # SEÑAL
    # ========================================================

    direction, probability, values =
        determine_signal(
            data
        )


    print()
    print("=" * 60)

    print(
        f"REUNIÓN: {meeting_date}"
    )

    print(
        f"🔴 ALZA: "
        f"{values['ALZA']:.1f}%"
    )

    print(
        f"🟢 RECORTE: "
        f"{values['RECORTE']:.1f}%"
    )

    print(
        f"⚪ MANTENER: "
        f"{values['MANTENER']:.1f}%"
    )

    print(
        f"SEÑAL: "
        f"{direction} "
        f"{probability:.1f}%"
    )

    print("=" * 60)


    # ========================================================
    # ESTADO
    # ========================================================

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
        f"Alerta: "
        f"{'SÍ' if alert else 'NO'}"
    )

    print(
        f"Motivo: {reason}"
    )


    # ========================================================
    # ENVIAR
    # ========================================================

    if alert:

        sent =
            send_ntfy(
                direction,
                probability,
                meeting_date,
                values,
                reason
            )


        if sent:

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
                "✓ Estado guardado."
            )

    else:

        print(
            "No se envía notificación."
        )


    print(
        "Proceso terminado."
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print("=" * 60)
        print("ERROR")
        print("=" * 60)
        print(
            str(error)
        )

        sys.exit(1)