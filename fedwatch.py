#!/usr/bin/env python3

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from datetime import date, datetime, timezone
from pathlib import Path


# ============================================================
# CONFIGURACIÓN
# ============================================================

CME_URL = "https://www.cmegroup.cn/fed-watch/"

THRESHOLD = 65.0
CHANGE = 10.0

STATE = Path("fedwatch_state.json")


# ============================================================
# UTILIDADES
# ============================================================

def pct(x):
    """
    Convierte valores como:
        93%
        <93%
        >93%
        ≈93%
    en float.
    """
    try:
        return float(
            str(x)
            .replace("%", "")
            .replace("<", "")
            .replace(">", "")
            .replace("≈", "")
            .strip()
        )
    except Exception:
        return 0.0


def date_parse(s):
    """
    Convierte fechas encontradas en diferentes formatos
    a YYYY-MM-DD.
    """

    s = (s or "").strip()

    # --------------------------------------------------------
    # Formato chino:
    # 16 9月 2026
    # --------------------------------------------------------

    m = re.match(
        r"(\d{1,2})\s*(\d{1,2})月\s*(\d{2,4})",
        s
    )

    if m:
        d, mo, y = map(int, m.groups())

        if y < 100:
            y += 2000

        return f"{y:04d}-{mo:02d}-{d:02d}"

    # --------------------------------------------------------
    # Formato:
    # 16 Sep 2026
    # --------------------------------------------------------

    m = re.match(
        r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2,4})",
        s
    )

    if m:
        d = m.group(1)
        mon = m.group(2)
        y = int(m.group(3))

        if y < 100:
            y += 2000

        try:
            month_number = datetime.strptime(
                mon,
                "%b"
            ).month

            return (
                f"{y:04d}-"
                f"{month_number:02d}-"
                f"{int(d):02d}"
            )

        except Exception:
            pass

    return ""


# ============================================================
# PARSER DE TEXTO
# ============================================================

def parse_text(text):

    info = {}

    # --------------------------------------------------------
    # Meeting date / contract / mid price
    # --------------------------------------------------------

    m = re.search(
        r"(\d{1,2}\s*\d{1,2}月\s*\d{4})\s+"
        r"(\w+)\s+"
        r"(\d{1,2}\s*\d{1,2}月\s*\d{4})\s+"
        r"([\d.]+)",
        text
    )

    if not m:

        m = re.search(
            r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+"
            r"(\w+)\s+"
            r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+"
            r"([\d.]+)",
            text
        )

    if m:

        info.update(
            meeting_date=date_parse(m.group(1)),
            contract=m.group(2),
            mid_price=m.group(4)
        )

    # --------------------------------------------------------
    # Current target rate
    # --------------------------------------------------------

    t = re.search(
        r"Current target rate is (\d+-\d+)",
        text,
        re.I
    )

    if t:
        info["current_target"] = t.group(1)

    # --------------------------------------------------------
    # Summary:
    # EASE / NO CHANGE / HIKE
    # --------------------------------------------------------

    summary = {}

    lines = text.splitlines()

    for i, line in enumerate(lines):

        if re.match(
            r"EASE\s+NO\s*CHANGE\s+HIKE",
            line.strip(),
            re.I
        ):

            for nxt in lines[i + 1:i + 4]:

                a = re.findall(
                    r"[\d.]+\s*%",
                    nxt
                )

                if len(a) >= 3:

                    summary = {
                        "ease": pct(a[0]),
                        "no_change": pct(a[1]),
                        "hike": pct(a[2])
                    }

                break

            break

    # --------------------------------------------------------
    # Tabla de probabilidades
    # --------------------------------------------------------

    table = []

    header = False
    sub = False

    for line in lines:

        s = line.strip()

        if (
            "TARGET RATE" in s.upper()
            and
            "PROBABILITY" in s.upper()
        ):
            header = True
            continue

        if header and not sub:

            if (
                "NOW" in s.upper()
                or
                "1 DAY" in s.upper()
            ):
                sub = True

            continue

        if not (header and sub and s):
            continue

        # ----------------------------------------------------
        # Formato tabulado
        # ----------------------------------------------------

        m = re.match(
            r"^(\d+-\d+(?:\s*\(Current\))?)\t(.+)$",
            s
        )

        if m:

            c = re.split(
                r"\t+",
                m.group(2)
            )

            table.append(
                {
                    "range": m.group(1),
                    "now": pct(c[0]) if len(c) > 0 else 0,
                    "day1": pct(c[1]) if len(c) > 1 else 0
                }
            )

        # ----------------------------------------------------
        # Formato separado por espacios
        # ----------------------------------------------------

        elif re.match(
            r"^\d+-\d+",
            s
        ):

            p = re.split(
                r"\s+",
                s
            )

            j = next(
                (
                    i
                    for i, x in enumerate(p)
                    if "%" in x
                ),
                None
            )

            if j is not None:

                table.append(
                    {
                        "range": " ".join(p[:j]),
                        "now": pct(p[j]),
                        "day1": (
                            pct(p[j + 1])
                            if len(p) > j + 1
                            else 0
                        )
                    }
                )

        if (
            s.startswith("* Data")
            or
            s.startswith("Powered by")
        ):
            break

    return info, summary, table


# ============================================================
# EXTRACCIÓN DIRECTA DEL DOM
# ============================================================

def dom_extract(frame):

    return frame.evaluate(
        r"""
        () => {

            const find = t => {

                for (
                    const x of document.querySelectorAll(
                        'table.grid-thm'
                    )
                ) {

                    const z = [
                        ...x.querySelectorAll('th,td')
                    ]
                    .map(e => e.textContent.trim())
                    .join(' ');

                    if (z.includes(t)) {
                        return x;
                    }
                }

                return null;
            };


            const pp = s => {

                const m = (s || '')
                    .replace(/[%<>≈\u200b]/g, '')
                    .match(/[\d.]+/);

                return m
                    ? parseFloat(m[0])
                    : 0;
            };


            const r = {
                meeting_date: '',
                contract: '',
                mid_price: '',
                current_target: '',
                summary: {},
                table: []
            };


            // ------------------------------------------------
            // Meeting Date
            // ------------------------------------------------

            const a = find('Meeting Date');

            if (a) {

                const c = a.querySelectorAll('td');

                if (c.length >= 4) {

                    r.meeting_date =
                        c[0].textContent.trim();

                    r.contract =
                        c[1].textContent.trim();

                    r.mid_price =
                        c[3].textContent.trim();
                }
            }


            // ------------------------------------------------
            // Probabilities
            // ------------------------------------------------

            const b = find('Probabilities');

            if (b) {

                for (
                    const row of b.querySelectorAll('tr')
                ) {

                    const c =
                        row.querySelectorAll('td');

                    if (c.length >= 3) {

                        r.summary = {
                            ease: pp(
                                c[0].textContent
                            ),

                            no_change: pp(
                                c[1].textContent
                            ),

                            hike: pp(
                                c[2].textContent
                            )
                        };
                    }
                }
            }


            // ------------------------------------------------
            // Target Rate
            // ------------------------------------------------

            const q = find('Target Rate (bps)');

            if (q) {

                for (
                    const row of q.querySelectorAll('tr')
                ) {

                    if (
                        row.classList.contains('hide')
                    ) {
                        continue;
                    }

                    const c =
                        row.querySelectorAll('td');

                    if (
                        c.length >= 2
                        &&
                        /^\d+-\d+/.test(
                            c[0].textContent.trim()
                        )
                    ) {

                        r.table.push(
                            {
                                range:
                                    c[0]
                                    .textContent
                                    .trim(),

                                now:
                                    pp(
                                        c[1]
                                        .textContent
                                    ),

                                day1:
                                    pp(
                                        c[2]?.textContent
                                    )
                            }
                        );
                    }
                }
            }


            // ------------------------------------------------
            // Current target rate
            // ------------------------------------------------

            for (
                const e of document.querySelectorAll('*')
            ) {

                const m =
                    e.textContent.match(
                        /Current target rate is (\d+-\d+)/i
                    );

                if (m) {

                    r.current_target = m[1];

                    break;
                }
            }


            return r;
        }
        """
    )


# ============================================================
# SCRAPER CME
# ============================================================

def scrape():

    from playwright.sync_api import (
        sync_playwright,
        TimeoutError as PWTimeout
    )

    out = []

    with sync_playwright() as p:

        # ----------------------------------------------------
        # Abrir navegador
        # ----------------------------------------------------

        b = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        page = b.new_page(
            viewport={
                "width": 1920,
                "height": 1080
            },

            user_agent=(
                "Mozilla/5.0 "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            )
        )

        # ----------------------------------------------------
        # Navegar a CME
        # ----------------------------------------------------

        try:

            page.goto(
                CME_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except PWTimeout:

            print(
                "Navigation timeout; "
                "continuing to wait for QuikStrike."
            )

        # ----------------------------------------------------
        # Buscar frame que contiene QuikStrike
        # ----------------------------------------------------

        frame = None

        end = time.time() + 90

        while time.time() < end and not frame:

            for f in page.frames:

                try:

                    tx = f.inner_text("body")

                    if (
                        "EASE" in tx
                        and
                        len(tx) > 500
                    ):

                        frame = f
                        break

                except Exception:
                    pass

            if not frame:

                time.sleep(5)

        if not frame:

            b.close()

            raise RuntimeError(
                "QuikStrike did not render."
            )

        # ----------------------------------------------------
        # Buscar pestañas de reuniones FOMC
        # ----------------------------------------------------

        tabs = frame.evaluate(
            """
            () => [
                ...document.querySelectorAll(
                    'a[id*="lbMeeting"]'
                )
            ].map(
                a => ({
                    id: a.id,
                    text: a.textContent.trim()
                })
            )
            """
        )

        if not tabs:

            b.close()

            raise RuntimeError(
                "No FOMC meeting tabs found."
            )

        # ----------------------------------------------------
        # Procesar cada reunión
        # ----------------------------------------------------

        for tab in tabs:

            try:

                ok = frame.evaluate(
                    """
                    id => {

                        const e =
                            document.getElementById(id);

                        if (e) {

                            e.click();

                            return true;
                        }

                        return false;
                    }
                    """,
                    tab["id"]
                )

                if not ok:
                    continue

                # ------------------------------------------------
                # Esperar a que cargue
                # ------------------------------------------------

                for _ in range(40):

                    time.sleep(0.3)

                    ready = frame.evaluate(
                        """
                        () => {

                            const t =
                                document.querySelector(
                                    '.throbber,[class*="loading"]'
                                );

                            return (
                                !t
                                ||
                                t.offsetParent === null
                            );
                        }
                        """
                    )

                    if ready:
                        break

                # ------------------------------------------------
                # Extraer datos
                # ------------------------------------------------

                d = dom_extract(frame)

                # ------------------------------------------------
                # Fallback de texto
                # ------------------------------------------------

                if not d.get("table"):

                    (
                        info,
                        summary,
                        table
                    ) = parse_text(
                        frame.inner_text("body")
                    )

                    d.update(
                        meeting_date=
                            info.get(
                                "meeting_date",
                                ""
                            ),

                        contract=
                            info.get(
                                "contract",
                                ""
                            ),

                        mid_price=
                            info.get(
                                "mid_price",
                                ""
                            ),

                        current_target=
                            info.get(
                                "current_target",
                                ""
                            ),

                        summary=summary,
                        table=table
                    )

                else:

                    d["meeting_date"] = date_parse(
                        d.get(
                            "meeting_date",
                            ""
                        )
                    )

                # ------------------------------------------------
                # Último fallback: texto de pestaña
                # ------------------------------------------------

                if not d.get("meeting_date"):

                    d["meeting_date"] = date_parse(
                        tab["text"]
                    )

                # ------------------------------------------------
                # Guardar reunión válida
                # ------------------------------------------------

                if (
                    d.get("meeting_date")
                    and
                    d.get("table")
                ):

                    out.append(d)

                print(
                    d.get("meeting_date"),
                    d.get("summary")
                )

            except Exception as e:

                print(
                    "Tab error:",
                    e
                )

        b.close()

    return out


# ============================================================
# CARGAR ESTADO ANTERIOR
# ============================================================

def state_load():

    try:

        if STATE.exists():

            return json.loads(
                STATE.read_text(
                    encoding="utf-8"
                )
            )

        return {}

    except Exception:

        return {}


# ============================================================
# ENVIAR NOTIFICACIÓN NTFY
# ============================================================

def notify(msg):

    topic = os.environ.get(
        "NTFY_TOPIC",
        ""
    ).strip()

    # --------------------------------------------------------
    # Comprobar secret
    # --------------------------------------------------------

    if not topic:

        raise RuntimeError(
            "Missing GitHub Secret NTFY_TOPIC."
        )

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    url = f"https://ntfy.sh/{topic}"

    # --------------------------------------------------------
    # Convertir mensaje
    # --------------------------------------------------------

    data = msg.encode(
        "utf-8"
    )

    # --------------------------------------------------------
    # Crear petición
    # --------------------------------------------------------

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Title": "CME FedWatch",
            "Priority": "high",
            "Tags": "chart_with_upwards_trend",
            "Content-Type":
                "text/plain; charset=utf-8"
        }
    )

    # --------------------------------------------------------
    # Enviar
    # --------------------------------------------------------

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            status = response.status

            body = response.read().decode(
                "utf-8",
                errors="replace"
            )

            print(
                f"NTFY HTTP STATUS: {status}"
            )

            print(
                f"NTFY RESPONSE: {body}"
            )

            if status < 200 or status >= 300:

                raise RuntimeError(
                    f"ntfy returned HTTP {status}"
                )

    # --------------------------------------------------------
    # Error HTTP
    # --------------------------------------------------------

    except urllib.error.HTTPError as e:

        body = e.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"ntfy HTTP ERROR {e.code}: {body}"
        )

    # --------------------------------------------------------
    # Error conexión
    # --------------------------------------------------------

    except urllib.error.URLError as e:

        raise RuntimeError(
            f"ntfy CONNECTION ERROR: {e.reason}"
        )


# ============================================================
# PROCESAR FEDWATCH
# ============================================================

def main():

    print("=" * 60)
    print("          CME FEDWATCH MONITOR")
    print("=" * 60)

    print()
    print(
        f"Umbral configurado: {THRESHOLD:.1f}%"
    )

    print(
        f"Cambio mínimo para alerta: {CHANGE:.1f} puntos"
    )

    print()

    # --------------------------------------------------------
    # Obtener reuniones
    # --------------------------------------------------------

    meetings = scrape()

    # --------------------------------------------------------
    # Fecha actual
    # --------------------------------------------------------

    today = date.today().isoformat()

    # --------------------------------------------------------
    # Filtrar reuniones futuras
    # --------------------------------------------------------

    future = [
        x
        for x in meetings
        if x.get(
            "meeting_date",
            ""
        ) >= today
    ]

    if not future:

        raise RuntimeError(
            "No future FOMC meeting found."
        )

    # --------------------------------------------------------
    # Próxima reunión
    # --------------------------------------------------------

    m = min(
        future,
        key=lambda x: x["meeting_date"]
    )

    # --------------------------------------------------------
    # Probabilidades
    # --------------------------------------------------------

    s = m.get(
        "summary",
        {}
    )

    vals = {
        "hike":
            float(
                s.get(
                    "hike",
                    0
                )
            ),

        "hold":
            float(
                s.get(
                    "no_change",
                    0
                )
            ),

        "cut":
            float(
                s.get(
                    "ease",
                    0
                )
            )
    }

    # --------------------------------------------------------
    # Determinar escenario dominante
    # --------------------------------------------------------

    direction = max(
        vals,
        key=vals.get
    )

    prob = vals[direction]

    # --------------------------------------------------------
    # Etiqueta
    # --------------------------------------------------------

    emoji, label = {
        "hike": (
            "🔴",
            "ALZA"
        ),

        "cut": (
            "🟢",
            "RECORTE"
        ),

        "hold": (
            "⚪",
            "MANTENER"
        )
    }[direction]

    # --------------------------------------------------------
    # Estado anterior
    # --------------------------------------------------------

    old = state_load()

    same = (
        old.get("meeting_date")
        ==
        m["meeting_date"]
    )

    prev = (
        float(
            old