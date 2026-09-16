import os
import re
import json
import time
import requests

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURACIÓN
# ============================================================

UMBRAL_ALERTA = 65.0
DELTA_MINIMO_CAMBIO = 10.0

STATE_FILE = "last_state.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

CME_URL = (
    "https://www.cmegroup.com/"
    "markets/interest-rates/"
    "cme-fedwatch-tool.html"
)


# ============================================================
# ESTADO
# ============================================================

def load_last_state():

    if not os.path.exists(STATE_FILE):
        return None

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(f"ERROR leyendo estado: {e}")

        return None


def save_state(
    event,
    value,
    rate,
    meeting_date
):

    data = {

        "event": event,

        "value": round(
            float(value),
            1
        ),

        "rate": rate,

        "meeting_date": meeting_date

    }

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("Estado guardado correctamente.")


# ============================================================
# NTFY
# ============================================================

def send_ntfy(
    title,
    message
):

    if not NTFY_TOPIC:

        raise RuntimeError(
            "La variable NTFY_TOPIC no existe."
        )

    url = (
        f"https://ntfy.sh/"
        f"{NTFY_TOPIC}"
    )

    print("")
    print("ENVIANDO NOTIFICACIÓN NTFY...")
    print(
        "URL: https://ntfy.sh/[TOPIC OCULTO]"
    )

    response = requests.post(

        url,

        data=message.encode(
            "utf-8"
        ),

        headers={

            "Title": title,

            "Priority": "high",

            "Tags":
                "chart_with_upwards_trend"

        },

        timeout=30

    )

    print(
        f"Respuesta ntfy HTTP: "
        f"{response.status_code}"
    )

    print(
        f"Respuesta ntfy: "
        f"{response.text[:500]}"
    )

    response.raise_for_status()

    print(
        "NOTIFICACIÓN NTFY ENVIADA CORRECTAMENTE."
    )


# ============================================================
# DIRECCIÓN
# ============================================================

def determine_direction(
    current_target,
    target_rate
):

    try:

        current_match = re.search(
            r"(\d+\.\d+)\s*%",
            current_target
        )

        target_match = re.search(
            r"(\d+\.\d+)\s*%",
            target_rate
        )

        if not current_match:
            return "CAMBIO"

        if not target_match:
            return "CAMBIO"

        current_rate = float(
            current_match.group(1)
        )

        target_rate_value = float(
            target_match.group(1)
        )

        if target_rate_value > current_rate:

            return "ALZA"

        if target_rate_value < current_rate:

            return "RECORTE"

        return "MANTENER"

    except Exception:

        return "CAMBIO"


# ============================================================
# FECHA
# ============================================================

def extract_meeting_date(text):

    match = re.search(
        r"\b(20\d{2}-\d{2}-\d{2})\b",
        text
    )

    if match:
        return match.group(1)

    match = re.search(
        r"\b"
        r"(0?[1-9]|1[0-2])"
        r"[\/\-]"
        r"(0?[1-9]|[12]\d|3[01])"
        r"[\/\-]"
        r"(20\d{2})"
        r"\b",
        text
    )

    if match:
        return match.group(0)

    match = re.search(
        r"\b"
        r"(January|February|March|April|May|June|"
        r"July|August|September|October|November|December)"
        r"\s+"
        r"\d{1,2}"
        r"(?:,\s*|\s+)"
        r"20\d{2}"
        r"\b",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(0)

    return "desconocida"


# ============================================================
# PROBABILIDADES
# ============================================================

def find_probability_candidates(text):

    candidates = []

    # --------------------------------------------------------
    # Ejemplo:
    #
    # 3.50%-3.75% 18.0%
    # 3.75%-4.00% 82.0%
    # --------------------------------------------------------

    pattern1 = re.compile(

        r"(\d+\.\d+)"
        r"\s*%"
        r"\s*[-–]"
        r"\s*"
        r"(\d+\.\d+)"
        r"\s*%"
        r"[\s:|]+"
        r"(\d+(?:\.\d+)?)"
        r"\s*%"

    )

    for match in pattern1.finditer(text):

        low = match.group(1)

        high = match.group(2)

        probability = float(
            match.group(3)
        )

        rate = (
            f"{low}%-{high}%"
        )

        if 0 <= probability <= 100:

            candidate = {

                "rate": rate,

                "probability":
                    probability

            }

            if candidate not in candidates:

                candidates.append(
                    candidate
                )


    # --------------------------------------------------------
    # Variante:
    #
    # 3.75 - 4.00 92.4%
    # --------------------------------------------------------

    pattern2 = re.compile(

        r"(\d+\.\d+)"
        r"\s*[-–]"
        r"\s*"
        r"(\d+\.\d+)"
        r"\s*"
        r"(\d+(?:\.\d+)?)"
        r"\s*%"

    )

    for match in pattern2.finditer(text):

        low = match.group(1)

        high = match.group(2)

        probability = float(
            match.group(3)
        )

        rate = (
            f"{low}%-{high}%"
        )

        if 0 <= probability <= 100:

            candidate = {

                "rate": rate,

                "probability":
                    probability

            }

            if candidate not in candidates:

                candidates.append(
                    candidate
                )

    return candidates


# ============================================================
# LEER PÁGINA + IFRAMES
# ============================================================

def collect_page_text(page):

    texts = []

    # --------------------------------------------------------
    # PÁGINA PRINCIPAL
    # --------------------------------------------------------

    try:

        main_text = page.locator(
            "body"
        ).inner_text(
            timeout=30000
        )

        if main_text:

            texts.append(
                main_text
            )

    except Exception as e:

        print(
            f"ERROR leyendo página principal: "
            f"{e}"
        )


    # --------------------------------------------------------
    # IFRAMES
    # --------------------------------------------------------

    print("")
    print(
        f"Iframes encontrados: "
        f"{len(page.frames)}"
    )

    for index, frame in enumerate(
        page.frames
    ):

        if frame == page.main_frame:
            continue

        try:

            print(
                f"Leyendo iframe {index}: "
                f"{frame.url[:200]}"
            )

            frame_text = frame.locator(
                "body"
            ).inner_text(
                timeout=15000
            )

            if frame_text:

                print(
                    f"Caracteres iframe: "
                    f"{len(frame_text)}"
                )

                texts.append(
                    frame_text
                )

        except Exception as e:

            print(
                f"ERROR leyendo iframe: "
                f"{e}"
            )

    return "\n".join(texts)


# ============================================================
# ABRIR CME
# ============================================================

def get_cme_text():

    print("")
    print("=" * 70)
    print("ABRIENDO CME FEDWATCH CON PLAYWRIGHT")
    print("=" * 70)

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=True,

            args=[

                "--no-sandbox",

                "--disable-dev-shm-usage",

                "--disable-gpu",

                "--disable-http2",

                "--disable-quic",

                "--disable-blink-features="
                "AutomationControlled",

                "--window-size=1920,1080"

            ]

        )

        context = browser.new_context(

            viewport={
                "width": 1920,
                "height": 1080
            },

            locale="en-US",

            timezone_id="America/New_York",

            user_agent=(

                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/128.0.0.0 "
                "Safari/537.36"

            ),

            extra_http_headers={

                "Accept-Language":
                    "en-US,en;q=0.9",

                "Upgrade-Insecure-Requests":
                    "1"

            }

        )

        page = context.new_page()


        # ----------------------------------------------------
        # BLOQUEAR RECURSOS PESADOS
        # ----------------------------------------------------

        def handle_route(route):

            resource = (
                route.request.resource_type
            )

            if resource in [

                "image",

                "font",

                "media"

            ]:

                route.abort()

            else:

                route.continue_()


        page.route(
            "**/*",
            handle_route
        )


        # ----------------------------------------------------
        # CARGAR CME
        # ----------------------------------------------------

        loaded = False

        last_error = None

        for attempt in range(1, 4):

            print("")
            print(
                f"INTENTO CME {attempt}/3"
            )

            try:

                response = page.goto(

                    CME_URL,

                    wait_until="commit",

                    timeout=60000

                )

                if response:

                    print(
                        f"HTTP CME: "
                        f"{response.status}"
                    )

                page.wait_for_timeout(
                    10000
                )

                text = collect_page_text(
                    page
                )

                print(
                    f"Caracteres obtenidos: "
                    f"{len(text)}"
                )

                if len(text) > 500:

                    loaded = True

                    print(
                        "CME cargó correctamente."
                    )

                    break

                print(
                    "CME cargó pero "
                    "hay poco contenido."
                )

            except Exception as e:

                last_error = e

                print(
                    f"ERROR intento {attempt}: "
                    f"{e}"
                )

                if attempt < 3:

                    time.sleep(5)


        if not loaded:

            try:

                page.screenshot(
                    path="cme_error.png",
                    full_page=True
                )

            except Exception:
                pass

            browser.close()

            raise RuntimeError(
                "CME no pudo ser cargado."
            ) from last_error


        # ----------------------------------------------------
        # ESPERAR CONTENIDO DINÁMICO
        # ----------------------------------------------------

        print("")
        print(
            "Esperando FedWatch / QuikStrike..."
        )

        page.wait_for_timeout(
            10000
        )

        text = collect_page_text(
            page
        )

        page.wait_for_timeout(
            10000
        )

        text = collect_page_text(
            page
        )


        # ----------------------------------------------------
        # DEBUG
        # ----------------------------------------------------

        with open(
            "cme_debug.txt",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(text)


        print("")
        print("=" * 70)
        print("LÍNEAS RELEVANTES")
        print("=" * 70)

        count = 0

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            lower = line.lower()

            if (

                "%" in line

                or "fedwatch" in lower

                or "fed watch" in lower

                or "2026" in line

                or "2027" in line

                or "2028" in line

            ):

                print(line)

                count += 1

                if count >= 150:

                    break

        print("=" * 70)

        browser.close()

        return text


# ============================================================
# FEDWATCH
# ============================================================

def get_fedwatch():

    text = get_cme_text()

    candidates = (
        find_probability_candidates(
            text
        )
    )

    print("")
    print("=" * 70)
    print("PROBABILIDADES DETECTADAS")
    print("=" * 70)

    for candidate in candidates:

        print(
            f"{candidate['rate']} "
            f"→ "
            f"{candidate['probability']:.1f}%"
        )

    print("=" * 70)

    if not candidates:

        raise RuntimeError(
            "No se encontraron probabilidades."
        )


    candidates.sort(
        key=lambda x: x["probability"],
        reverse=True
    )

    best = candidates[0]

    meeting_date = (
        extract_meeting_date(
            text
        )
    )


    # --------------------------------------------------------
    # TASA ACTUAL
    # --------------------------------------------------------

    current_target = "desconocida"

    patterns = [

        r"current\s+target"
        r".{0,100}?"
        r"(\d+\.\d+%\s*[-–]\s*"
        r"\d+\.\d+%)",

        r"current\s+rate"
        r".{0,100}?"
        r"(\d+\.\d+%\s*[-–]\s*"
        r"\d+\.\d+%)",

        r"target\s+rate"
        r".{0,100}?"
        r"(\d+\.\d+%\s*[-–]\s*"
        r"\d+\.\d+%)"

    ]

    for pattern in patterns:

        match = re.search(

            pattern,

            text,

            re.IGNORECASE |
            re.DOTALL

        )

        if match:

            current_target = (
                match.group(1)
                .replace(
                    " ",
                    ""
                )
            )

            break


    # --------------------------------------------------------
    # SI NO ENCUENTRA TASA ACTUAL
    # --------------------------------------------------------

    if current_target == "desconocida":

        match = re.search(

            r"(\d+\.\d+%)"
            r"\s*[-–]"
            r"\s*(\d+\.\d+%)",

            text

        )

        if match:

            current_target = (

                f"{match.group(1)}-"
                f"{match.group(2)}"

            )


    event = determine_direction(

        current_target,

        best["rate"]

    )


    return {

        "meeting_date":
            meeting_date,

        "current_target":
            current_target,

        "event":
            event,

        "rate":
            best["rate"],

        "probability":
            best["probability"]

    }


# ============================================================
# MONITOR
# ============================================================

def check_fedwatch():

    print("")
    print("=" * 70)
    print("CME FEDWATCH MONITOR")
    print("=" * 70)

    data = get_fedwatch()

    meeting_date = (
        data["meeting_date"]
    )

    current_target = (
        data["current_target"]
    )

    event = data["event"]

    rate = data["rate"]

    value = float(
        data["probability"]
    )


    print("")
    print("=" * 70)
    print("RESULTADO ACTUAL")
    print("=" * 70)

    print(
        f"Próxima reunión: "
        f"{meeting_date}"
    )

    print(
        f"Tasa actual: "
        f"{current_target}"
    )

    print(
        f"Dirección: "
        f"{event}"
    )

    print(
        f"Objetivo: "
        f"{rate}"
    )

    print(
        f"Probabilidad: "
        f"{value:.1f}%"
    )

    print("=" * 70)


    # --------------------------------------------------------
    # MENOR A 65
    # --------------------------------------------------------

    if value < UMBRAL_ALERTA:

        print("")
        print(
            f"NO HAY ALERTA: "
            f"{value:.1f}% < "
            f"{UMBRAL_ALERTA:.1f}%"
        )

        return


    # --------------------------------------------------------
    # ESTADO ANTERIOR
    # --------------------------------------------------------

    last_state = (
        load_last_state()
    )

    if last_state is None:

        last_event = None
        last_value = 0.0
        last_rate = None
        last_meeting = None

    else:

        last_event = (
            last_state.get(
                "event"
            )
        )

        last_value = float(

            last_state.get(
                "value",
                0
            )

        )

        last_rate = (
            last_state.get(
                "rate"
            )
        )

        last_meeting = (
            last_state.get(
                "meeting_date"
            )
        )


    print("")
    print("=" * 70)
    print("ESTADO ANTERIOR")
    print("=" * 70)

    print(
        f"Dirección: "
        f"{last_event}"
    )

    print(
        f"Probabilidad: "
        f"{last_value:.1f}%"
    )

    print(
        f"Objetivo: "
        f"{last_rate}"
    )

    print(
        f"Reunión: "
        f"{last_meeting}"
    )

    print("=" * 70)


    # --------------------------------------------------------
    # DECIDIR SI ALERTAR
    # --------------------------------------------------------

    send_alert = False

    reason = ""


    if last_event is None:

        send_alert = True

        reason = (
            "Primera señal detectada."
        )


    elif (
        last_meeting
        and
        meeting_date != last_meeting
    ):

        send_alert = True

        reason = (
            "Cambió la próxima "
            "reunión."
        )


    elif event != last_event:

        send_alert = True

        reason = (

            f"Cambio de dirección: "
            f"{last_event} → {event}"

        )


    elif (
        abs(value - last_value)
        >= DELTA_MINIMO_CAMBIO
    ):

        send_alert = True

        reason = (

            f"Cambio de "
            f"{abs(value - last_value):.1f} "
            f"puntos porcentuales."

        )


    if not send_alert:

        print("")
        print(
            "SIN CAMBIO SIGNIFICATIVO"
        )

        print(
            f"Variación: "
            f"{value - last_value:+.1f} puntos"
        )

        print(
            f"Se requieren: "
            f"{DELTA_MINIMO_CAMBIO:.1f} puntos"
        )

        return


    # --------------------------------------------------------
    # ICONO
    # --------------------------------------------------------

    if event == "ALZA":

        icon = "🔴"

    elif event == "RECORTE":

        icon = "🟢"

    else:

        icon = "⚪"


    # --------------------------------------------------------
    # MENSAJE
    # --------------------------------------------------------

    title = (

        f"FEDWATCH > "
        f"{UMBRAL_ALERTA:.0f}% - "
        f"{event}"

    )


    message = (

        "CME FEDWATCH\n\n"

        f"Proxima reunion: "
        f"{meeting_date}\n\n"

        f"Tasa actual: "
        f"{current_target}\n\n"

        f"{icon} {event}\n\n"

        f"Objetivo: "
        f"{rate}\n"

        f"Probabilidad: "
        f"{value:.1f}%\n\n"

        f"Anterior: "
        f"{last_value:.1f}%\n"

        f"Cambio: "
        f"{value - last_value:+.1f} "
        f"puntos\n\n"

        f"Motivo: "
        f"{reason}\n\n"

        f"Umbral: "
        f"{UMBRAL_ALERTA:.0f}%\n"

        f"Minimo cambio: "
        f"{DELTA_MINIMO_CAMBIO:.0f} "
        f"puntos"

    )


    print("")
    print("=" * 70)
    print("ALERTA")
    print("=" * 70)

    print(message)

    print("=" * 70)


    # --------------------------------------------------------
    # NTFY
    # --------------------------------------------------------

    send_ntfy(
        title,
        message
    )


    # --------------------------------------------------------
    # GUARDAR ESTADO
    # SOLO SI NTFY FUNCIONÓ
    # --------------------------------------------------------

    save_state(

        event,

        value,

        rate,

        meeting_date

    )


    print("")
    print("=" * 70)
    print("ALERTA ENVIADA")
    print("ESTADO GUARDADO")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("")
    print("=" * 70)
    print("INICIANDO FEDWATCH.PY")
    print("=" * 70)

    try:

        check_fedwatch()

    except Exception as e:

        print("")
        print("=" * 70)
        print("ERROR FATAL")
        print("=" * 70)

        print(
            repr(e)
        )

        print("=" * 70)

        raise