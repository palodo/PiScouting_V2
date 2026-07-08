"""Rastreo del calendario FEB (ASP.NET WebForms) para listar todos los partidos.

Devuelve, por competición y temporada, la lista de partidos con: grupo, jornada,
fecha, resultado, equipos (nombre + URL Equipo.aspx?i=) y partido_id. Adaptado del
scraper original del proyecto, parametrizado y sin escritura a CSV.
"""
from __future__ import annotations

import re
import time
import random
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from ..config import FEB_BASE, USER_AGENT

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

JORNADA_Y_FECHA_RE = re.compile(r"jornada\s*(\d+)\s+(\d{2}/\d{2}/\d{4})", re.I)
JORNADA_SOLO_RE = re.compile(r"jornada\s*(\d+)", re.I)
RESULTADO_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _serialize_form(soup: BeautifulSoup, base_url: str):
    form = (soup.select_one("form#aspnetForm") or soup.select_one("form[name='aspnetForm']")
            or soup.select_one("form"))
    if not form:
        raise RuntimeError("No se encontró el formulario aspnetForm")
    action = urljoin(base_url, form.get("action") or base_url)
    data: dict[str, str] = {}
    for inp in form.select("input[name]"):
        name = inp.get("name")
        typ = (inp.get("type") or "").lower()
        if typ in ("checkbox", "radio"):
            if inp.has_attr("checked"):
                data[name] = inp.get("value", "on")
        else:
            data[name] = inp.get("value", "")
    for sel in form.select("select[name]"):
        opt = sel.select_one("option[selected]") or sel.select_one("option")
        data[sel.get("name")] = opt.get("value", "") if opt is not None else ""
    return action, data, form


def _eventtarget(sel) -> str:
    onchange = sel.get("onchange") or ""
    m = re.search(r"__doPostBack\('([^']+)'", onchange)
    if m:
        return m.group(1)
    if sel.get("id"):
        return sel.get("id").replace("_", "$")
    return (sel.get("name") or "").replace(":", "$")


def _find_select(form, keywords):
    for sel in form.select("select[name]"):
        texts = " | ".join(o.get_text(strip=True) for o in sel.select("option")[:40]).lower()
        if any(k in texts for k in keywords):
            return sel
    return None


def _maybe_delta(html: str) -> str:
    if html and html.count("|") > 5 and ("updatePanel" in html or "hiddenField" in html):
        parts = html.split("|")
        frags = [parts[i + 2] for i in range(len(parts) - 2) if parts[i] == "updatePanel"]
        if frags:
            return "".join(frags)
    return html


def _postback(session, action, payload, eventtarget, field_name, field_value, referer):
    p = dict(payload)
    p["__EVENTTARGET"] = eventtarget
    p["__EVENTARGUMENT"] = ""
    p["__ASYNCPOST"] = "true"
    if field_name:
        p[field_name] = field_value
    headers = {**HEADERS, "X-MicrosoftAjax": "Delta=true", "Referer": referer}
    r = session.post(action, data=p, headers=headers, timeout=30)
    r.raise_for_status()
    time.sleep(random.uniform(0.4, 0.9))
    return _maybe_delta(r.text)


def _parse_matches(html: str, grupo: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    columnas = soup.select("div.columna")
    for columna in columnas:
        h1 = columna.select_one("h1.titulo-modulo")
        jornada, fecha_col = None, None
        if h1:
            t = _norm(h1.get_text())
            m = JORNADA_Y_FECHA_RE.search(t)
            if m:
                jornada, fecha_col = f"Jornada {m.group(1)}", m.group(2)
            else:
                m2 = JORNADA_SOLO_RE.search(t)
                jornada = f"Jornada {m2.group(1)}" if m2 else t
        tabla = columna.select_one("table")
        if not tabla:
            continue
        for tr in tabla.select("tbody tr") or tabla.select("tr"):
            a_part = tr.select_one(
                "td.fecha a[href*='Partido.aspx?p='], td.resultado a[href*='Partido.aspx?p=']"
            )
            partido_url = urljoin(FEB_BASE, a_part.get("href")) if a_part else None
            partido_id = None
            if partido_url:
                q = parse_qs(urlparse(partido_url).query)
                partido_id = (q.get("p") or [None])[0]
            a_local = tr.select_one("td.equipo.local a[href*='Equipo.aspx?i=']")
            a_visit = tr.select_one("td.equipo.visitante a[href*='Equipo.aspx?i=']")
            local = _norm(a_local.get_text()) if a_local else None
            visit = _norm(a_visit.get_text()) if a_visit else None
            local_url = urljoin(FEB_BASE, a_local.get("href")) if a_local else None
            visit_url = urljoin(FEB_BASE, a_visit.get("href")) if a_visit else None
            resultado = None
            td_res = tr.select_one("td.resultado")
            if td_res:
                mr = RESULTADO_RE.search(_norm(td_res.get_text()))
                if mr:
                    resultado = f"{mr.group(1)}-{mr.group(2)}"
            if local and visit and local != visit and partido_id:
                mnum = re.search(r"(\d+)", jornada or "")
                rows.append({
                    "grupo": grupo, "jornada": jornada,
                    "jornada_num": int(mnum.group(1)) if mnum else None,
                    "fecha": fecha_col, "resultado": resultado,
                    "local": local, "local_url": local_url,
                    "visitante": visit, "visitante_url": visit_url,
                    "partido_id": partido_id, "partido_url": partido_url,
                })
    return rows


def crawl_calendar(calendar_slug: str, season: str, group_code: int = 1) -> list[dict]:
    """Rastrea todos los grupos y jornadas de una URL de calendario FEB.

    calendar_slug: p.ej. 'primerafeb', 'segundafeb', 'tercerafeb'
    group_code: subdivisión de la URL /calendario/<slug>/<group_code>/<season>
    """
    url = f"{FEB_BASE}/calendario/{calendar_slug}/{group_code}/{season}"
    session = requests.Session()
    session.headers.update(HEADERS)
    r = session.get(url, timeout=30)
    r.raise_for_status()
    if not r.encoding:
        r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "lxml")
    action, payload, form = _serialize_form(soup, url)

    sel_groups = _find_select(form, ["liga regular", "fase final", "eliminatoria", "grupo"])
    all_rows: list[dict] = []

    group_options = []
    if sel_groups:
        for o in sel_groups.select("option"):
            val, lab = (o.get("value") or "").strip(), o.get_text(strip=True)
            if val:
                group_options.append((val, lab, o.has_attr("selected")))
    if not group_options:
        group_options = [("", "Único", True)]

    g_name = sel_groups.get("name") if sel_groups else None
    g_et = _eventtarget(sel_groups) if sel_groups else None
    html_base = r.text

    for gval, glabel, is_default in group_options:
        if is_default or not sel_groups:
            html_group = html_base
        else:
            html_group = _postback(session, action, payload, g_et, g_name, gval, url)
        soup_g = BeautifulSoup(html_group, "lxml")
        try:
            action, payload_g, form_g = _serialize_form(soup_g, url)
        except Exception:
            payload_g, form_g = dict(payload), form

        sel_j = _find_select(form_g, ["jornada"])
        if sel_j:
            j_name = sel_j.get("name")
            j_et = _eventtarget(sel_j)
            j_opts = [((o.get("value") or "").strip(), o.get_text(strip=True), o.has_attr("selected"))
                      for o in sel_j.select("option") if (o.get("value") or "").strip()]
            for ji, (jval, jlab, is_j_def) in enumerate(j_opts):
                if is_j_def and (is_default or not sel_groups):
                    html_j = html_group
                else:
                    html_j = _postback(session, action, payload_g, j_et, j_name, jval, url)
                rows = _parse_matches(html_j, glabel)
                for rr in rows:
                    if not rr.get("jornada"):
                        rr["jornada"] = jlab
                all_rows.extend(rows)
                try:
                    action, payload_g, _ = _serialize_form(BeautifulSoup(html_j, "lxml"), url)
                except Exception:
                    pass
        else:
            all_rows.extend(_parse_matches(html_group, glabel))

        if not is_default and sel_groups:
            try:
                action, payload, form = _serialize_form(BeautifulSoup(html_group, "lxml"), url)
            except Exception:
                pass

    # Dedup por partido_id
    seen, dedup = set(), []
    for rr in all_rows:
        pid = rr["partido_id"]
        if pid not in seen:
            seen.add(pid)
            dedup.append(rr)
    return dedup
