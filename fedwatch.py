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
                "--disable-blink-features=AutomationControlled"
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
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),

            extra_http_headers={
                "Accept-Language":
                    "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests":
                    "1"
            }
        )

        page = context.new_page()

        # ====================================================
        # BLOQUEAR SOLO RECURSOS PESADOS
        # ====================================================

        def handle_route(route):

            resource = route.request.resource_type

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

        # ====================================================
        # URL PRINCIPAL
        # ====================================================

        url = (
            "https://www.cmegroup.com/"
            "markets/interest-rates/"
            "cme-fedwatch-tool.html"
        )

        loaded = False

        # ====================================================
        # REINTENTAR 3 VECES
        # ====================================================

        for attempt in range(1, 4):

            try:

                print("")
                print(
                    f"Intento CME {attempt}/3"
                )

                response = page.goto(
                    url,
                    wait_until="commit",
                    timeout=60000
                )

                print(
                    f"HTTP CME: "
                    f"{response.status if response else 'sin respuesta'}"
                )

                # Esperar que el documento avance
                page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=30000
                )

                page.wait_for_timeout(10000)

                text = page.locator(
                    "body"
                ).inner_text(
                    timeout=30000
                )

                print(
                    f"Caracteres obtenidos: "
                    f"{len(text)}"
                )

                if len(text) > 500:

                    loaded = True

                    print("")
                    print(
                        "✅ CME cargó correctamente."
                    )

                    break

            except Exception as e:

                print("")
                print(
                    f"⚠️ Intento {attempt} falló:"
                )

                print(e)

                if attempt < 3:

                    page.wait_for_timeout(5000)

        # ====================================================
        # SI NO CARGÓ
        # ====================================================

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
                "CME no pudo ser cargado después "
                "de 3 intentos."
            )

        # ====================================================
        # ESPERAR FEDWATCH
        # ====================================================

        print("")
        print(
            "Esperando renderizado de FedWatch..."
        )

        page.wait_for_timeout(15000)

        text = page.locator(
            "body"
        ).inner_text()

        # ====================================================
        # GUARDAR TEXTO PARA DIAGNÓSTICO
        # ====================================================

        with open(
            "cme_debug.txt",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(text)

        print("")
        print(
            f"Texto final CME: "
            f"{len(text)} caracteres"
        )

        # ====================================================
        # MOSTRAR LÍNEAS IMPORTANTES
        # ====================================================

        print("")
        print(
            "LÍNEAS RELEVANTES:"
        )

        print("-" * 70)

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            if (
                "%" in line
                or "FedWatch" in line
                or "FEDWATCH" in line
                or "2026" in line
                or "2027" in line
            ):

                print(line)

        print("-" * 70)

        browser.close()

        return text