"""
GPS Petrópolis — Servidor Flask
Uso: python server.py  (ou duplo clique em rodar.bat)
"""
import json, os, heapq, webbrowser, threading
import requests as req_lib
from flask import Flask, jsonify, request, send_from_directory

# ── Config ────────────────────────────────────────────────────
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA2ZWE3NjcxYzY0MTRjMTZhZThmOWI4NTM5YTYwMjQ4IiwiaCI6Im11cm11cjY0In0="
ORS_URL     = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
PORT        = 5000
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# ── Grafo ─────────────────────────────────────────────────────
try:
    with open(os.path.join(BASE_DIR, "grafo_completo_coords.json"), encoding="utf-8") as f:
        grafo = json.load(f)
    print(f"[OK] {len(grafo)} nos carregados")
except Exception as e:
    print(f"[ERRO] grafo: {e}")
    grafo = {}

# ── Lógica ───────────────────────────────────────────────────
def classificar_horario(h):
    try:
        h = int(h.split(":")[0])
        if   h <  5: return "madrugada"
        elif h <  7: return "leve"
        elif h < 10: return "pico_manha"
        elif h < 16: return "normal"
        elif h < 19: return "pico_tarde"
        elif h < 22: return "moderado"
        else:        return "noite"
    except:
        return "normal"

def calcular_peso(a, ctx):
    if ctx["veiculo"] == "truck" and a.get("caminhao", 1) == 0:
        return float("inf"), "bloqueado"
    if ctx["chuva"] >= 3 and a.get("hidr", 0) >= 6:
        return float("inf"), "bloqueado"
    if ctx["chuva"] >= 4 and a.get("hidr", 0) >= 5:
        return float("inf"), "bloqueado"
    if ctx["chuva"] >= 4 and a.get("geol", 0) >= 8:
        return float("inf"), "bloqueado"
    peso = float(a["distancia"])
    peso += (a.get("hidr", 0) ** 2) * (ctx["chuva"] ** 2)
    peso += (a.get("geol", 0) ** 2) *  ctx["chuva"]
    if ctx["horario"] == "noite":
        peso += a.get("social", 0) * 20
    if ctx["horario"] in ("pico_manha", "pico_tarde"):
        peso *= 1.5
    elif ctx["horario"] == "moderado":
        peso *= 1.2
    return peso, "explorado"

def dijkstra(origem, destino, ctx):
    if origem not in grafo or destino not in grafo:
        return None, []
    dist, prev = {origem: 0.0}, {}
    queue, visitados, historico = [(0.0, origem)], set(), []
    while queue:
        custo, u = heapq.heappop(queue)
        if u in visitados: continue
        visitados.add(u)
        if u == destino: break
        if u not in grafo: continue
        for a in grafo[u]["arestas"]:
            v = a["destino"]
            peso, tipo = calcular_peso(a, ctx)
            historico.append({
                "u": u, "v": v,
                "lat_u": grafo[u]["lat"], "lng_u": grafo[u]["lng"],
                "lat_v": a["lat"],        "lng_v": a["lng"],
                "tipo": tipo,
            })
            if v not in visitados and peso != float("inf"):
                novo = custo + peso
                if novo < dist.get(v, float("inf")):
                    dist[v] = novo; prev[v] = u
                    heapq.heappush(queue, (novo, v))
    if destino not in prev and destino != origem:
        return None, historico
    cam, cur = [], destino
    while cur in prev:
        cam.append(cur); cur = prev[cur]
    cam.append(origem); cam.reverse()
    pares = set(zip(cam, cam[1:]))
    for h in historico:
        if (h["u"], h["v"]) in pares:
            h["tipo"] = "finalizado"
    return cam, historico

def buscar_ors(cam):
    if len(cam) < 2:
        return None
    rota = []
    for i in range(len(cam) - 1):
        u, v = cam[i], cam[i+1]
        coords = [[grafo[u]["lng"], grafo[u]["lat"]], [grafo[v]["lng"], grafo[v]["lat"]]]
        try:
            r = req_lib.post(ORS_URL,
                json={"coordinates": coords, "instructions": False, "geometry": True},
                headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
                timeout=8)
            if r.status_code != 200:
                print(f"[ORS] {r.status_code}: {r.text[:80]}")
                return None
            pts = r.json()["features"][0]["geometry"]["coordinates"]
            rota.extend([[c[1], c[0]] for c in pts])
        except Exception as e:
            print(f"[ORS] {e}")
            return None
    return rota or None

# ── Rotas Flask ───────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/<path:fn>")
def arquivos(fn):
    return send_from_directory(BASE_DIR, fn)

@app.route("/api/pontos")
def api_pontos():
    return jsonify(sorted(grafo.keys()))

@app.route("/api/grafo")
def api_grafo():
    return jsonify({
        nome: {
            "lat": d["lat"], "lng": d["lng"],
            "arestas": [
                {"destino": a["destino"], "lat": a["lat"], "lng": a["lng"],
                 "caminhao": a.get("caminhao", 1), "hidr": a.get("hidr", 0),
                 "geol": a.get("geol", 0)}
                for a in d.get("arestas", [])
            ]
        }
        for nome, d in grafo.items()
    })

@app.route("/api/calcular", methods=["POST"])
def api_calcular():
    d       = request.get_json()
    origem  = d.get("origem", "")
    destino = d.get("destino", "")
    hora    = d.get("hora", "08:00")
    chuva   = int(d.get("chuva", 0))
    veiculo = d.get("veiculo", "car")
    print(f"[calcular] {origem} -> {destino} | chuva={chuva} | {veiculo}")
    if origem not in grafo or destino not in grafo:
        return jsonify({"status": "erro", "mensagem": "No nao encontrado."})
    ctx = {"horario": classificar_horario(hora), "chuva": chuva, "veiculo": veiculo}
    cam, hist = dijkstra(origem, destino, ctx)
    if cam is None:
        return jsonify({"status": "sem_rota", "historico": hist,
                        "mensagem": "Nenhuma rota com as condicoes atuais."})
    dist_total = sum(
        next((a["distancia"] for a in grafo[cam[i]]["arestas"] if a["destino"] == cam[i+1]), 0)
        for i in range(len(cam)-1)
    )
    poly = buscar_ors(cam)
    via_ors = poly is not None
    if not via_ors:
        poly = [[grafo[p]["lat"], grafo[p]["lng"]] for p in cam]
    return jsonify({
        "status": "ok",
        "caminho_nos": cam,
        "polyline": poly,
        "historico": hist,
        "distancia_total": round(dist_total, 1),
        "via_ors": via_ors,
    })

# ── Iniciar ───────────────────────────────────────────────────
def abrir():
    import time; time.sleep(1.2)
    webbrowser.open(f"http://localhost:{PORT}")

if __name__ == "__main__":
    print(f"\n  GPS Petropolis - http://localhost:{PORT}\n")
    threading.Thread(target=abrir, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
