import os
import json
import requests
from datetime import date

from cme_fedwatch import get_probabilities


# ============================================================
# CONFIGURACIÓN
# ============================================================

UMBRAL_ALERTA = 65.0

# Nueva alerta solamente si cambia 10 puntos porcentuales
DELTA_MINIMO_CAMBIO = 10.0

STATE_FILE = "last_state.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")


# ============================================================
# NTFY
# ============================================================

def send_ntfy(title, message):

    if not NTFY_TOPIC:
        raise RuntimeError(
            "ERROR: NTFY_TOPIC no está configurado."
        )

    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    response = requests.post(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": "high",
            "Tags": "chart_with_upwards_trend",
        },
        timeout=30,
    )

    print("")
    print("=" * 70)
    print("RESPUESTA NTFY")
    print("=" * 70)

    print(
        f"HTTP: {response.status_code}"
    )

    print(
        response.text[:500]
    )

    print("=" * 70)

    response.raise_for_status()

    print("NTFY: NOTIFICACIÓN ENVIADA.")


# ============================================================
# ESTADO
# ============================================================

def load_state():

    if not os.path.exists(STATE_FILE):
        return None

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            return json.load(file)

    except Exception as error:

        print(
            f"ERROR leyendo estado: {error}"
        )

        return None


def save_state(
    event,
    probability,
    rate,
    meeting_date,
):

    data = {
        "event": event,
        "value": round(
            float(probability),
            1,
        ),
        "rate": rate,
        "meeting_date": meeting_date,
    }

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print("")
    print(
        "Estado guardado correctamente."
    )


# ============================================================
# DIRECCIÓN
# ============================================================

def determine_direction(
    current_target,
    target_rate,
):

    try:

        current_low = float(
            current_target.split("-")[0]
            .replace("%", "")
        )

        target_low = float(
            target_rate.split("-")[0]
            .replace("%", "")
        )

        if target_low > current_low:

            return "ALZA"

        if target_low < current_low:

            return "RECORTE"

        return "MANTENER"

    except Exception:

        return "CAMBIO"


# ============================================================
# OBTENER FEDWATCH
# ============================================================

def get_fedwatch():

    print("")
    print("=" * 70)
    print("CONSULTANDO CME FEDWATCH")
    print("=" * 70)

    print("")
    print(
        "Fuente: CME Fed Funds futures"
    )

    # --------------------------------------------------------
    # Pedimos la próxima reunión
    # --------------------------------------------------------

    data = get_probabilities("next")

    print("")
    print(
        "Datos recibidos correctamente."
    )

    print("")
    print(
        f"Estructura recibida: "
        f"{type(data).__name__}"
    )

    # --------------------------------------------------------
    # Datos generales
    # --------------------------------------------------------

    current_target = data.get(
        "current_target"
    )

    effr = data.get(
        "effr"
    )

    meetings = data.get(
        "meetings",
        []
    )

    print("")
    print(
        f"EFFR: {effr}"
    )

    print(
        f"Tasa objetivo actual: "
        f"{current_target}"
    )

    print(
        f"Reuniones encontradas: "
        f"{len(meetings)}"
    )

    if not meetings:

        raise RuntimeError(
            "No se encontraron reuniones FedWatch."
        )

    # --------------------------------------------------------
    # Primera reunión = próxima reunión
    # --------------------------------------------------------

    meeting = meetings[0]

    meeting_date = str(
        meeting.get("date")
    )

    probabilities = meeting.get(
        "probabilities",
        {}
    )

    if not probabilities:

        raise RuntimeError(
            "La próxima reunión no contiene probabilidades."
        )

    print("")
    print("=" * 70)
    print("PROBABILIDADES DETECTADAS")
    print("=" * 70)

    for rate, probability in probabilities.items():

        print(
            f"{rate} -> "
            f"{float(probability):.1f}%"
        )

    print("=" * 70)

    # --------------------------------------------------------
    # Encontrar la probabilidad más alta
    # --------------------------------------------------------

    best_rate = max(
        probabilities,
        key=lambda rate:
            float(probabilities[rate]),
    )

    best_probability = float(
        probabilities[best_rate]
    )

    event = determine_direction(
        current_target,
        best_rate,
    )

    return {

        "meeting_date":
            meeting_date,

        "current_target":
            current_target,

        "effr":
            effr,

        "event":
            event,

        "rate":
            best_rate,

        "probability":
            best_probability,

        "probabilities":
            probabilities,

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

    meeting_date = data[
        "meeting_date"
    ]

    current_target = data[
        "current_target"
    ]

    event = data[
        "event"
    ]

    rate = data[
        "rate"
    ]

    probability = float(
        data["probability"]
    )

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

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
        f"{probability:.1f}%"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # ¿SUPERÓ 65%?
    # --------------------------------------------------------

    if probability < UMBRAL_ALERTA:

        print("")
        print(
            f"NO HAY ALERTA."
        )

        print(
            f"{probability:.1f}% "
            f"< "
            f"{UMBRAL_ALERTA:.1f}%"
        )

        return

    # --------------------------------------------------------
    # ESTADO ANTERIOR
    # --------------------------------------------------------

    previous = load_state()

    if previous is None:

        previous_event = None
        previous_probability = 0.0
        previous_rate = None
        previous_meeting = None

    else:

        previous_event = previous.get(
            "event"
        )

        previous_probability = float(
            previous.get(
                "value",
                0,
            )
        )

        previous_rate = previous.get(
            "rate"
        )

        previous_meeting = previous.get(
            "meeting_date"
        )

    print("")
    print("=" * 70)
    print("ESTADO ANTERIOR")
    print("=" * 70)

    print(
        f"Dirección: "
        f"{previous_event}"
    )

    print(
        f"Probabilidad: "
        f"{previous_probability:.1f}%"
    )

    print(
        f"Objetivo: "
        f"{previous_rate}"
    )

    print(
        f"Reunión: "
        f"{previous_meeting}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # DECIDIR ALERTA
    # --------------------------------------------------------

    send_alert = False

    reason = ""

    # Primera señal
    if previous_event is None:

        send_alert = True

        reason = (
            "Primera señal >= 65%."
        )

    # Cambió reunión
    elif (
        previous_meeting
        and
        meeting_date != previous_meeting
    ):

        send_alert = True

        reason = (
            "Cambió la próxima reunión."
        )

    # Cambió dirección
    elif event != previous_event:

        send_alert = True

        reason = (
            f"Cambio de dirección: "
            f"{previous_event} -> {event}"
        )

    # Cambió 10 puntos
    elif (
        abs(
            probability
            - previous_probability
        )
        >= DELTA_MINIMO_CAMBIO
    ):

        send_alert = True

        reason = (
            f"Cambio de "
            f"{abs(probability - previous_probability):.1f} "
            f"puntos porcentuales."
        )

    # --------------------------------------------------------
    # NO ALERTA
    # --------------------------------------------------------

    if not send_alert:

        print("")
        print("=" * 70)
        print("SIN CAMBIO SIGNIFICATIVO")
        print("=" * 70)

        print(
            f"Anterior: "
            f"{previous_probability:.1f}%"
        )

        print(
            f"Actual: "
            f"{probability:.1f}%"
        )

        print(
            f"Cambio: "
            f"{probability - previous_probability:+.1f} puntos"
        )

        print(
            f"Se necesitan: "
            f"{DELTA_MINIMO_CAMBIO:.1f} puntos"
        )

        print("=" * 70)

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
        f"{probability:.1f}%\n\n"

        f"Anterior: "
        f"{previous_probability:.1f}%\n"

        f"Cambio: "
        f"{probability - previous_probability:+.1f} puntos\n\n"

        f"Motivo: "
        f"{reason}\n\n"

        f"Umbral: "
        f"{UMBRAL_ALERTA:.0f}%\n"

        f"Minimo cambio: "
        f"{DELTA_MINIMO_CAMBIO:.0f} puntos"

    )

    print("")
    print("=" * 70)
    print("ALERTA")
    print("=" * 70)

    print(message)

    print("=" * 70)

    # --------------------------------------------------------
    # ENVIAR
    # --------------------------------------------------------

    print("")
    print(
        "Enviando alerta ntfy..."
    )

    send_ntfy(
        title,
        message,
    )

    # --------------------------------------------------------
    # GUARDAR ESTADO
    # --------------------------------------------------------

    save_state(
        event,
        probability,
        rate,
        meeting_date,
    )

    print("")
    print("=" * 70)
    print("ALERTA ENVIADA CORRECTAMENTE")
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

    except Exception as error:

        print("")
        print("=" * 70)
        print("ERROR FATAL")
        print("=" * 70)

        print(
            repr(error)
        )

        print("=" * 70)

        raise