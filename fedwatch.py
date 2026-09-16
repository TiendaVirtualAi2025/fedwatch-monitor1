import requests

URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"

print("=" * 70)
print("PRUEBA DE CONEXIÓN CON CME")
print("=" * 70)

headers = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/128.0.0.0 "
        "Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

try:

    print("")
    print("Conectando con CME...")

    response = requests.get(
        URL,
        headers=headers,
        timeout=30
    )

    print("")
    print(f"HTTP: {response.status_code}")

    print(
        f"Caracteres recibidos: "
        f"{len(response.text)}"
    )

    print("")
    print("Primeros 1000 caracteres:")
    print("-" * 70)

    print(response.text[:1000])

    print("-" * 70)

    with open(
        "cme_test.html",
        "w",
        encoding="utf-8"
    ) as f:

        f.write(response.text)

    print("")
    print("Archivo cme_test.html guardado.")

except Exception as e:

    print("")
    print("=" * 70)
    print("ERROR")
    print("=" * 70)

    print(repr(e))

    raise