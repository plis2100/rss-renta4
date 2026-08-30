import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


WEB_URL = "https://www.renta4banco.com/es/noticias"
BASE_URL = "https://www.renta4banco.com"
ARCHIVO_RSS = Path("renta4.xml")

CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

MESES = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


def limpiar_texto(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def escapar_xml(texto):
    return (
        str(texto)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def descargar_pagina():
    respuesta = requests.get(
        WEB_URL,
        headers=CABECERAS,
        timeout=60,
        allow_redirects=True,
    )
    respuesta.raise_for_status()

    if not respuesta.text.strip():
        raise RuntimeError("Renta 4 devolvió una página vacía")

    return respuesta.text


def convertir_fecha(texto):
    coincidencia = re.search(
        r"\b(\d{1,2})\s+"
        r"(ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic)"
        r"\s+(\d{4})\b",
        texto.lower(),
    )

    if not coincidencia:
        return None

    dia = int(coincidencia.group(1))
    mes = MESES[coincidencia.group(2)]
    anio = int(coincidencia.group(3))

    try:
        return datetime(
            anio,
            mes,
            dia,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def es_enlace_de_noticia(url):
    ruta = urlparse(url).path.rstrip("/")

    if not ruta.startswith("/es/noticias/"):
        return False

    resto = ruta.removeprefix("/es/noticias/")

    if not resto:
        return False

    # Excluye las páginas de paginación: /es/noticias/2
    if resto.isdigit():
        return False

    return True


def buscar_contenedor(enlace):
    actual = enlace

    for _ in range(9):
        actual = actual.parent

        if actual is None:
            break

        texto = limpiar_texto(actual.get_text(" ", strip=True))

        if convertir_fecha(texto) is not None:
            if len(texto) <= 1600:
                return actual

    return None


def obtener_descripcion(contenedor, titulo):
    texto = limpiar_texto(contenedor.get_text(" ", strip=True))

    texto = texto.replace(titulo, " ")
    texto = re.sub(
        r"Noticias Renta 4 Banco",
        " ",
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(
        r"Departamento de Comunicación",
        " ",
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(
        r"\b\d{1,2}\s+"
        r"(?:ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic)"
        r"\s+\d{4}\b",
        " ",
        texto,
        flags=re.IGNORECASE,
    )
    texto = limpiar_texto(texto)

    return texto[:800]


def obtener_noticias(html):
    soup = BeautifulSoup(html, "html.parser")
    noticias = []
    enlaces_vistos = set()

    for enlace in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, enlace.get("href"))
        url = url.split("#")[0].split("?")[0].rstrip("/")

        if not es_enlace_de_noticia(url):
            continue

        if url in enlaces_vistos:
            continue

        titulo = limpiar_texto(enlace.get_text(" ", strip=True))

        if len(titulo) < 15:
            continue

        contenedor = buscar_contenedor(enlace)

        if contenedor is None:
            continue

        texto_contenedor = limpiar_texto(
            contenedor.get_text(" ", strip=True)
        )
        fecha = convertir_fecha(texto_contenedor)

        if fecha is None:
            continue

        descripcion = obtener_descripcion(
            contenedor,
            titulo,
        )

        noticias.append(
            {
                "titulo": titulo,
                "url": url,
                "fecha": fecha,
                "descripcion": descripcion,
            }
        )

        enlaces_vistos.add(url)

    noticias.sort(
        key=lambda noticia: noticia["fecha"],
        reverse=True,
    )

    if not noticias:
        raise RuntimeError(
            "No se encontraron noticias de Renta 4 Banco"
        )

    return noticias[:40]


def crear_rss(noticias):
    ahora = datetime.now(timezone.utc)

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        "<title>Renta 4 Banco - Noticias</title>",
        f"<link>{escapar_xml(WEB_URL)}</link>",
        (
            "<description>Últimas noticias oficiales publicadas "
            "por Renta 4 Banco</description>"
        ),
        "<language>es</language>",
        f"<lastBuildDate>{format_datetime(ahora)}</lastBuildDate>",
        "<ttl>60</ttl>",
    ]

    for noticia in noticias:
        partes.extend(
            [
                "<item>",
                f"<title>{escapar_xml(noticia['titulo'])}</title>",
                f"<link>{escapar_xml(noticia['url'])}</link>",
                (
                    f'<guid isPermaLink="true">'
                    f"{escapar_xml(noticia['url'])}</guid>"
                ),
                (
                    f"<pubDate>"
                    f"{format_datetime(noticia['fecha'])}"
                    f"</pubDate>"
                ),
                (
                    f"<description>"
                    f"{escapar_xml(noticia['descripcion'])}"
                    f"</description>"
                ),
                "</item>",
            ]
        )

    partes.extend(
        [
            "</channel>",
            "</rss>",
        ]
    )

    return "\n".join(partes)


def guardar_rss(contenido):
    archivo_temporal = ARCHIVO_RSS.with_suffix(".xml.tmp")
    archivo_temporal.write_text(
        contenido,
        encoding="utf-8",
    )
    archivo_temporal.replace(ARCHIVO_RSS)


def main():
    html = descargar_pagina()
    noticias = obtener_noticias(html)
    contenido_rss = crear_rss(noticias)
    guardar_rss(contenido_rss)

    print(
        f"RSS de Renta 4 actualizada: "
        f"{len(noticias)} noticias"
    )

    for noticia in noticias[:5]:
        print(
            noticia["fecha"].strftime("%d/%m/%Y"),
            "-",
            noticia["titulo"],
        )


if __name__ == "__main__":
    main()
