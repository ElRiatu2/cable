import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import subprocess
import urllib.request

# --- CONFIGURACIÓN DE XTREAM CODES ---
XTREAM_HOST = "http://aioplus.es:80"
XTREAM_USER = "ALAM5462"
XTREAM_PASS = "jVf3Q5Bg"

# --- CONFIGURACIÓN DE RUTAS ---
REPO_DIR = "/home/alam/jellyfin_ligamx"
XML_OUTPUT_PATH = os.path.join(REPO_DIR, "guia_leaguescup.xml")
M3U_OUTPUT_PATH = os.path.join(REPO_DIR, "cable.m3u8")

LOGO_CANAL = "https://brandlogos.net/wp-content/uploads/2025/02/leagues_cup-logo_brandlogos.net_gxi1m.png"

# Configuración API Jellyfin
JELLYFIN_URL = "http://localhost:8096"
JELLYFIN_TOKEN = "b06b770f7fc64107aef0ba2206b7af71"
TASK_REFRESH_CHANNELS = "0c9ee3a88fc15547c6852205480da1fd"
TASK_REFRESH_GUIDE = "bea9b218c97bbf98c5dc1303bdb9a0ca"

URL_STREAM_DEFAULT = f"{XTREAM_HOST}/live/{XTREAM_USER}/{XTREAM_PASS}/1.ts"

CANALES = [
    {"id": "LeaguesCup1", "name": "Leagues Cup 1"},
    {"id": "LeaguesCup2", "name": "Leagues Cup 2"},
    {"id": "LeaguesCup3", "name": "Leagues Cup 3"},
    {"id": "LeaguesCup4", "name": "Leagues Cup 4"}
]

def obtener_streams_xtream_dict():
    url_api = f"{XTREAM_HOST}/player_api.php?username={XTREAM_USER}&password={XTREAM_PASS}&action=get_live_streams"
    streams_leagues = []
    try:
        req = urllib.request.Request(url_api, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            for stream in data:
                name = stream.get('name', '').lower()
                if 'leagues cup' in name or ('leagues' in name and 'cup' in name):
                    stream_id = stream.get('stream_id')
                    if stream_id:
                        stream_url = f"{XTREAM_HOST}/live/{XTREAM_USER}/{XTREAM_PASS}/{stream_id}.ts"
                        streams_leagues.append({"name": name, "url": stream_url})
    except Exception as e:
        print(f"[Xtream] Error consultando API: {e}")
    return streams_leagues

def coincide_equipo(nombre_espn, nombre_xtream):
    palabras = [p for p in nombre_espn.lower().split() if len(p) > 2 and p not in ['club', 'fc', 'de', 'deportes']]
    for p in palabras:
        if p in nombre_xtream:
            return True
    return False

def obtener_partidos_leagues_cup():
    partidos = []
    tz_cst = timezone(timedelta(hours=-6))
    
    # Fecha actual CST
    hoy_dt = datetime.now(tz_cst)
    fecha_hoy = hoy_dt.strftime('%Y%m%d')
    fecha_manana = (hoy_dt + timedelta(days=1)).strftime('%Y%m%d')
    
    streams_disponibles = obtener_streams_xtream_dict()
    ids_procesados = set()

    for fecha_str in [fecha_hoy, fecha_manana]:
        urls = [
            f'https://site.web.api.espn.com/apis/site/v2/sports/soccer/concacaf.leagues/scoreboard?dates={fecha_str}',
            f'https://site.web.api.espn.com/apis/site/v2/sports/soccer/usa.leagues/scoreboard?dates={fecha_str}',
            f'https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={fecha_str}&limit=100'
        ]
        
        for url in urls:
            cmd = ['curl', '-sL', '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36', url]
            try:
                out = subprocess.check_output(cmd).decode('utf-8')
                data = json.loads(out)
                events = data.get('events', [])

                for e in events:
                    str_e = json.dumps(e).lower()
                    if 'leagues' in str_e:
                        comp = e.get('competitions', [{}])[0]
                        hora_utc_str = comp.get('date').replace('Z', '+00:00')
                        dt_utc = datetime.fromisoformat(hora_utc_str)
                        dt_cst = dt_utc.astimezone(tz_cst)
                        
                        # Filtrar solo eventos de hoy en adelante (no partidos viejos)
                        if dt_cst.date() < hoy_dt.date():
                            continue

                        competitors = comp.get('competitors', [])
                        home = competitors[0].get('team', {}).get('displayName', 'Local') if len(competitors) > 0 else 'Local'
                        away = competitors[1].get('team', {}).get('displayName', 'Visitante') if len(competitors) > 1 else 'Visitante'
                        
                        partido_id = f"{home}-{away}-{dt_utc.strftime('%Y%m%d%H%M')}"
                        if partido_id in ids_procesados:
                            continue
                        ids_procesados.add(partido_id)

                        fin_partido = dt_utc + timedelta(hours=2, minutes=15)
                        
                        partidos.append({
                            "id": partido_id,
                            "home": home,
                            "away": away,
                            "titulo": f"{home} vs. {away}",
                            "inicio": dt_utc,
                            "fin": fin_partido,
                            "url": None
                        })
            except Exception:
                pass

    partidos.sort(key=lambda x: x["inicio"])

    streams_libres = list(streams_disponibles)
    for p in partidos:
        match_idx = None
        for idx, st in enumerate(streams_libres):
            if coincide_equipo(p["home"], st["name"]) or coincide_equipo(p["away"], st["name"]):
                match_idx = idx
                break
        if match_idx is not None:
            p["url"] = streams_libres.pop(match_idx)["url"]

    for p in partidos:
        if not p["url"] and streams_libres:
            p["url"] = streams_libres.pop(0)["url"]

    return partidos, streams_disponibles

def distribuir_partidos(partidos):
    programacion = {ch["id"]: [] for ch in CANALES}
    fin_ocupado = {ch["id"]: datetime.min.replace(tzinfo=timezone.utc) for ch in CANALES}
    
    for partido in partidos:
        canal_asignado = None
        for ch in CANALES:
            ch_id = ch["id"]
            if fin_ocupado[ch_id] <= partido["inicio"]:
                canal_asignado = ch_id
                break

        if canal_asignado:
            programacion[canal_asignado].append(partido)
            fin_ocupado[canal_asignado] = partido["fin"]
            
    return programacion

def actualizar_cable_m3u(programacion, todos_los_streams):
    if not os.path.exists(M3U_OUTPUT_PATH):
        print(f"Error: No existe el archivo {M3U_OUTPUT_PATH}")
        return

    with open(M3U_OUTPUT_PATH, "r", encoding="utf-8") as f:
        lineas = f.readlines()

    urls_usadas = set()
    urls_activas = {}

    for ch in CANALES:
        ch_id = ch["id"]
        partidos_canal = programacion.get(ch_id, [])
        url_canal = None
        
        if partidos_canal and partidos_canal[0].get("url"):
            url_canal = partidos_canal[0]["url"]

        if not url_canal or url_canal in urls_usadas:
            for st in todos_los_streams:
                if st["url"] not in urls_usadas:
                    url_canal = st["url"]
                    break
        
        if not url_canal:
            url_canal = URL_STREAM_DEFAULT
            
        urls_usadas.add(url_canal)
        urls_activas[ch_id] = url_canal

    nuevas_lineas = []
    i = 0
    num_lineas = len(lineas)
    canales_encontrados = set()

    while i < num_lineas:
        linea = lineas[i]
        canal_match = None

        for ch in CANALES:
            if f'tvg-id="{ch["id"]}"' in linea or f'group-title="Leagues Cup",{ch["name"]}' in linea:
                canal_match = ch
                break

        if canal_match:
            ch_id = canal_match["id"]
            canales_encontrados.add(ch_id)
            
            nuevas_lineas.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{canal_match["name"]}" tvg-logo="{LOGO_CANAL}" group-title="Leagues Cup",{canal_match["name"]}\n')
            nuevas_lineas.append(f'{urls_activas[ch_id]}\n')

            if i + 1 < num_lineas and not lineas[i + 1].startswith("#"):
                i += 2
            else:
                i += 1
        else:
            nuevas_lineas.append(linea)
            i += 1

    for ch in CANALES:
        ch_id = ch["id"]
        if ch_id not in canales_encontrados:
            nuevas_lineas.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{ch["name"]}" tvg-logo="{LOGO_CANAL}" group-title="Leagues Cup",{ch["name"]}\n')
            nuevas_lineas.append(f'{urls_activas[ch_id]}\n')

    with open(M3U_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.writelines(nuevas_lineas)

def construir_xmltv(programacion):
    tv = ET.Element("tv", {"generator-info-name": "GeneradorLeaguesCup"})
    for ch in CANALES:
        channel = ET.SubElement(tv, "channel", id=ch["id"])
        ET.SubElement(channel, "display-name").text = ch["name"]
        ET.SubElement(channel, "icon", src=LOGO_CANAL)
        
    ahora_utc = datetime.now(timezone.utc)
    inicio_bloque = ahora_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_bloque = inicio_bloque + timedelta(days=2)

    for ch in CANALES:
        ch_id = ch["id"]
        cursor = inicio_bloque
        
        partidos_ch = sorted(programacion.get(ch_id, []), key=lambda x: x["inicio"])
        
        for p in partidos_ch:
            if p["fin"] <= cursor:
                continue
            if p["inicio"] > cursor:
                crear_relleno(tv, ch_id, cursor, p["inicio"])
            
            prog = ET.SubElement(tv, "programme", {
                "start": p["inicio"].strftime("%Y%m%d%H%M%S +0000"),
                "stop": p["fin"].strftime("%Y%m%d%H%M%S +0000"),
                "channel": ch_id
            })
            ET.SubElement(prog, "title", lang="es").text = f"{p['titulo']} (En Vivo)"
            ET.SubElement(prog, "desc", lang="es").text = f"Partido en vivo de la Leagues Cup: {p['titulo']}."
            ET.SubElement(prog, "category", lang="es").text = "Deportes"
            cursor = p["fin"]
            
        if cursor < fin_bloque:
            crear_relleno(tv, ch_id, cursor, fin_bloque)
        
    tree = ET.ElementTree(tv)
    ET.indent(tree, space="  ", level=0)
    with open(XML_OUTPUT_PATH, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)
    print("Guía XMLTV (guia_leaguescup.xml) generada correctamente.")

def crear_relleno(tv_element, ch_id, inicio, fin):
    if inicio >= fin:
        return
    prog = ET.SubElement(tv_element, "programme", {
        "start": inicio.strftime("%Y%m%d%H%M%S +0000"),
        "stop": fin.strftime("%Y%m%d%H%M%S +0000"),
        "channel": ch_id
    })
    ET.SubElement(prog, "title", lang="es").text = "Leagues Cup 2026 - Transmisión en Vivo"
    ET.SubElement(prog, "desc", lang="es").text = "Transmisiones, análisis y resúmenes de la Leagues Cup."
    ET.SubElement(prog, "category", lang="es").text = "Deportes"

def subir_a_github():
    try:
        subprocess.run(["git", "add", "guia_leaguescup.xml", "cable.m3u8"], cwd=REPO_DIR, check=True)
        res = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_DIR, capture_output=True, text=True)
        if res.stdout.strip():
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
            subprocess.run(["git", "commit", "-m", f"Auto-update Leagues Cup: {fecha}"], cwd=REPO_DIR, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=REPO_DIR, check=True)
            print("¡Push realizado a GitHub con éxito!")
        return True
    except Exception as e:
        print(f"Error Git: {e}")
        return False

def refrescar_jellyfin():
    import time
    print("[Jellyfin] Esperando 5 segundos...")
    time.sleep(5)
    print("[Jellyfin] Solicitando refresco de canales y guía TV...")
    for task_id in [TASK_REFRESH_CHANNELS, TASK_REFRESH_GUIDE]:
        cmd = [
            'curl', '-s', '-X', 'POST',
            f"{JELLYFIN_URL}/ScheduledTasks/Running/{task_id}",
            '-H', f"X-Emby-Token: {JELLYFIN_TOKEN}"
        ]
        try:
            subprocess.run(cmd, check=False)
        except Exception as e:
            print(f"[Jellyfin] Error ejecutando curl: {e}")

if __name__ == "__main__":
    partidos, todos_los_streams = obtener_partidos_leagues_cup()
    programacion = distribuir_partidos(partidos)
    
    construir_xmltv(programacion)
    actualizar_cable_m3u(programacion, todos_los_streams)
    
    if subir_a_github():
        refrescar_jellyfin()
