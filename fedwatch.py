import os
import re
import json
import requests

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURACIÓN
# ============================================================

UMBRAL_ALERTA = 65.0
DELTA_MINIMO_CAMBIO = 10.0

STATE_FILE = "last_state.json"

NTFY_TOPIC = os.environ["NTFY_TOPIC"]


# ============================================================
# URLS CME
# ============================================================

CME_URLS = [
    "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    "https://www.cmegroup.com/cn/fed-watch/"
]


# ============================================================
# ESTADO
# ============================================================

def load_last_state():

    if not os.path.exists(STATE_FILE):
        return None

    try:

        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    except Exception as e:

        print(f"⚠️ No se pudo leer el estado: {e}")

        return None


def save_state(event, value, rate, meeting_date):

    data = {
        "event": event,
        "value": round(value, 1),
        "rate": rate,
        "meeting_date": meeting_date
    }

    with open(STATE_FILE, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# NTFY
# ============================================================

def send_ntfy(title, message):

    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    response = requests.post(

        url,

        data=message.encode("utf-8"),

        headers={
            "Title": title,
            "Priority": "high",
            "Tags": "chart_with_upwards_trend"
        },

        timeout=30
    )

    response.raise_for_status()

    print("✅ ntfy confirmó el envío.")


# ============================================================
# DIRECCIÓN
# ============================================================

def determine_direction(current_target, target_rate):

    try:

        current_upper = float(
            current_target
            .split("-")[1]
            .replace("%", "")
        )

        target_upper = float(
            target_rate
            .split("-")[1]
            .replace("%", "")
        )

        if target_upper > current_upper:
            return "ALZA"

        if target_upper < current_upper:
            return "RECORTE"

        return "MANTENER"

    except Exception:

        return "CAMBIO"


# ============================================================
# EXTRAER PORCENTAJES
# ============================================================

def extract_probabilities(text):

    """
    Busca estructuras como:

    3.50%-3.75%    7.6%
    3.75%-4.00%   92.4%

    También acepta espacios entre los números.
    """

    pattern = re.compile(
        r"(\d+\.\d+)\s*%\s*[-–]\s*"
        r"(\d+\.\d+)\s*%\s+"
        r"(\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE
    )

    matches = pattern.findall(text)

    probabilities = []

    for low, high, probability in matches:

        rate = f"{low}%-{high}%"

        probabilities.append(
            (
                rate,
                float(probability)
            )
        )

    return probabilities


# ============================================================
# BUSCAR PROBABILIDADES EN TEXTO
# ============================================================

def find_probability_candidates(text):

    candidates = []

    # --------------------------------------------------------
    # Forma normal:
    #
    # 3.50%-3.75% 18%
    # 3.75%-4.00% 82%
    # --------------------------------------------------------

    pattern1 = re.compile(
        r"(\d+\.\d+)\s*%\s*[-–]\s*"
        r"(\d+\.\d+)\s*%"
        r"[\s:|]+"
        r"(\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE
    )

    for match in pattern1.finditer(text):

        low = match.group(1)
        high = match.group(2)
        probability = float(match.group(3))

        rate = f"{low}%-{high}%"

        if 0 <= probability <= 100:

            candidates.append(
                {
                    "rate": rate,
                    "probability": probability
                }
            )

    # --------------------------------------------------------
    # Forma alternativa:
    #
    # 3.75 - 4.00 92.4%
    # --------------------------------------------------------

    pattern2 = re.compile(
        r"(\d+\.\d+)\s*[-–]\s*"
        r"(\d+\.\d+)"
        r"[\s:|]+"
        r"(\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE
    )

    for match in pattern2.finditer(text):

        low = match.group(1)
        high = match.group(2)
        probability = float(match.group(3))

        rate = f"{low}%-{high}%"

        if 0 <= probability <= 100:

            candidate = {
                "rate": rate,
                "probability": probability
            }

            if candidate not in candidates:

                candidates.append(candidate)

    return candidates


# ============================================================
# EXTRAER FECHA
# ============================================================

def extract_meeting_date(text):

    patterns = [

        r"\b(20\d{2}-\d{2}-\d{2})\b",

        r"\b(0?[1-9]|1[0-2])[/\-](0?[1-9]|[12]\d|3[01])[/\-](20\d{2})\b",

        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2}),?\s+(20\d{2})\b"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            if len(match.groups()) == 1:

                return match.group(1)

            return match.group(0)

    return "desconocida"


# ============================================================
# OBTENER TEXTO DE CME
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
                "--disable-gpu"
            ]
        )

        context = browser.new_context(

            viewport={
                "width": 1920,
                "height": 1080
            },

            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Bloquear recursos innecesarios
        # ----------------------------------------------------

        def handle_route(route):

            request = route.request

            resource = request.resource_type

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
        # Intentar las URLs
        # ----------------------------------------------------

        final_url = None

        for url in CME_URLS:

            try:

                print("")
                print(f"Intentando:")
                print(url)

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                # Esperar renderizado del widget
                page.wait_for_timeout(15000)

                text = page.locator("body").inner_text(
                    timeout=20000
                )

                print("")
                print(
                    f"Caracteres obtenidos: {len(text)}"
                )

                # ------------------------------------------------
                # Buscar indicios de FedWatch
                # ------------------------------------------------

                lower = text.lower()

                if (
                    "fedwatch" in lower
                    or "fed watch" in lower
                    or "%" in text
                ):

                    final_url = url

                    print("")
                    print("✅ Página CME cargada.")

                    break

            except Exception as e:

                print(
                    f"⚠️ Error con esta URL: {e}"
                )

        if final_url is None:

            browser.close()

            raise RuntimeError(
                "No fue posible cargar CME FedWatch."
            )

        # ----------------------------------------------------
        # Dar tiempo adicional al widget
        # ----------------------------------------------------

        page.wait_for_timeout(10000)

        text = page.locator("body").inner_text()

        # ----------------------------------------------------
        # Guardar HTML/texto para diagnóstico
        # ----------------------------------------------------

        try:

            with open(
                "cme_debug.txt",
                "w",
                encoding="utf-8"
            ) as f:

                f.write(text)

        except Exception:

            pass

        # ----------------------------------------------------
        # Mostrar fragmentos relacionados
        # ----------------------------------------------------

        lines = text.splitlines()

        relevant_lines = []

        for line in lines:

            line_clean = line.strip()

            if not line_clean:
                continue

            if (
                "%"
                in line_clean
                or "2026" in line_clean
                or "2027" in line_clean
                or "FedWatch" in line_clean
                or "FEDWATCH" in line_clean
            ):

                relevant_lines.append(
                    line_clean
                )

        print("")
        print("LÍNEAS RELEVANTES ENCONTRADAS:")
        print("-" * 70)

        for line in relevant_lines[:100]:

            print(line)

        print("-" * 70)

        browser.close()

        return text


# ============================================================
# OBTENER FEDWATCH
# ============================================================

def get_fedwatch():

    text = get_cme_text()

    # --------------------------------------------------------
    # Extraer candidatos
    # --------------------------------------------------------

    candidates = find_probability_candidates(text)

    print("")
    print("CANDIDATOS ENCONTRADOS:")
    print("-" * 70)

    for candidate in candidates:

        print(
            f"{candidate['rate']} "
            f"→ "
            f"{candidate['probability']:.1f}%"
        )

    print("-" * 70)

    if not candidates:

        raise RuntimeError(
            "Playwright cargó CME pero no encontró "
            "probabilidades de FedWatch."
        )

    # --------------------------------------------------------
    # El porcentaje mayor será la probabilidad dominante
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["probability"],
        reverse=True
    )

    best = candidates[0]

    meeting_date = extract_meeting_date(text)

    # --------------------------------------------------------
    # Intentar detectar tasa actual
    # --------------------------------------------------------

    current_target = None

    current_pattern = re.search(
        r"(\d+\.\d+)\s*%\s*[-–]\s*"
        r"(\d+\.\d+)\s*%",
        text
    )

    if current_pattern:

        current_target = (
            f"{current_pattern.group(1)}%-"
            f"{current_pattern.group(2)}%"
        )

    if current_target is None:

        current_target = "desconocida"

    # --------------------------------------------------------
    # Determinar dirección
    # --------------------------------------------------------

    event = determine_direction(
        current_target,
        best["rate"]
    )

    return {
        "meeting_date": meeting_date,
        "current_target": current_target,
        "event": event,
        "rate": best["rate"],
        "probability": best["probability"]
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

    meeting_date = data["meeting_date"]
    current_target = data["current_target"]
    event = data["event"]
    rate = data["rate"]
    value = data["probability"]

    print("")
    print("RESULTADO:")
    print("=" * 70)

    print(
        f"Próxima reunión: {meeting_date}"
    )

    print(
        f"Tasa actual: {current_target}"
    )

    print(
        f"Señal: {event}"
    )

    print(
        f"Objetivo: {rate}"
    )

    print(
        f"Probabilidad: {value:.1f}%"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # Estado anterior
    # --------------------------------------------------------

    last_state = load_last_state()

    if last_state is None:

        print("")
        print("No existe estado anterior.")

        last_event = None
        last_value = 0.0
        last_rate = None

    else:

        last_event = last_state.get(
            "event"
        )

        last_value = float(
            last_state.get(
                "value",
                0
            )
        )

        last_rate = last_state.get(
            "rate"
        )

        print("")
        print("ESTADO ANTERIOR:")
        print(
            f"{last_event} → "
            f"{last_value:.1f}%"
        )

    # --------------------------------------------------------
    # Decidir alerta
    # --------------------------------------------------------

    send_alert = False

    reason = ""

    # Primera señal
    if last_event is None:

        send_alert = True

        reason = "Primera señal detectada."

    # Cambio de dirección
    elif event != last_event:

        send_alert = True

        reason = (
            f"Cambio de dirección: "
            f"{last_event} → {event}"
        )

    # Cambio de probabilidad >= 5
    elif abs(value - last_value) >= DELTA_MINIMO_CAMBIO:

        send_alert = True

        reason = (
            f"Cambio de "
            f"{abs(value - last_value):.1f} "
            f"puntos porcentuales."
        )

    else:

        print("")
        print(
            "⚪ SIN CAMBIO SIGNIFICATIVO"
        )

        print(
            f"Variación: "
            f"{value - last_value:+.1f} puntos"
        )

        return

    # --------------------------------------------------------
    # Color
    # --------------------------------------------------------

    if event == "ALZA":

        icon = "🔴"

    elif event == "RECORTE":

        icon = "🟢"

    else:

        icon = "⚪"

    # --------------------------------------------------------
    # Mensaje
    # --------------------------------------------------------

    title = (
        f"FEDWATCH > {UMBRAL_ALERTA}% - {event}"
    )

    message = (

        "CME FEDWATCH\n\n"

        f"Proxima reunion: "
        f"{meeting_date}\n\n"

        f"Tasa actual: "
        f"{current_target}\n\n"

        f"{icon} {event}\n"

        f"Objetivo: "
        f"{rate}\n"

        f"Probabilidad: "
        f"{value:.1f}%\n\n"

        f"Anterior: "
        f"{last_value:.1f}%\n"

        f"Cambio: "
        f"{value - last_value:+.1f} puntos\n\n"

        f"Motivo: "
        f"{reason}\n\n"

        f"Umbral: "
        f"{UMBRAL_ALERTA}%"
    )

    print("")
    print(message)

    # --------------------------------------------------------
    # Enviar
    # --------------------------------------------------------

    print("")
    print("Enviando ntfy...")

    send_ntfy(
        title,
        message
    )

    # --------------------------------------------------------
    # Guardar SOLO si ntfy funcionó
    # --------------------------------------------------------

    save_state(
        event,
        value,
        rate,
        meeting_date
    )

    print("")
    print("=" * 70)
    print("✅ ALERTA ENVIADA Y ESTADO GUARDADO")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    check_fedwatch()