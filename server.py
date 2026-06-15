import json
import os
import heapq
import math
import requests as req_lib
from flask import Flask, jsonify, request, send_from_directory

ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA2ZWE3NjcxYzY0MTRjMTZhZThmOWI4NTM5YTYwMjQ4IiwiaCI6Im11cm11cjY0In0="
ORS_URL     = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
PORT     = 5000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

def carregar_json(nome_arquivo):
    caminho = os.path.join(BASE_DIR, nome_arquivo)
    if not os.path.exists(caminho):
        raise FileNotFoundError(f"Arquivo não encontrado: {nome_arquivo}")
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)

GRAFO_JSON = carregar_json("nos_e_arestas.json")
PARAMS     = carregar_json("parametros.json")

def graus_para_radianos(graus):
    return (graus * math.pi) / 180

def calcular_distancia_haversine(lat1, lon1, lat2, lon2):
    raio_terra = PARAMS["constantes"]["raio_terra_m"]
    delta_lat  = lat2 - lat1
    delta_lon  = lon2 - lon1
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2)
    return 2 * raio_terra * math.asin(math.sqrt(a))

def calcular_distancia_segmentos(pontos_rad):
    total = 0.0
    for i in range(len(pontos_rad) - 1):
        lat1, lon1 = pontos_rad[i]
        lat2, lon2 = pontos_rad[i + 1]
        total += calcular_distancia_haversine(lat1, lon1, lat2, lon2)
    return total

def obter_peso(lista, id_valor):
    for item in lista:
        if item["id"] == id_valor:
            return item["peso"]
    return 1.0

def classificar_hora(hora_str):
    for faixa in PARAMS["hora"]:
        if faixa["inicio"] <= hora_str <= faixa["fim"]:
            return faixa["id"]
    return 4

def montar_grafo():
    grafo = {}
    for id_no, dados in GRAFO_JSON["nos"].items():
        grafo[int(id_no)] = {
            "nome":      dados["nome"],
            "lat":       graus_para_radianos(dados["lat"]),
            "lon":       graus_para_radianos(dados["lon"]),
            "lat_graus": dados["lat"],
            "lon_graus": dados["lon"],
            "arestas":   []
        }

    geometrias = GRAFO_JSON.get("geometria", {})

    for a in GRAFO_JSON["arestas"]:
        origem  = a["origem"]
        destino = a["destino"]
        if origem not in grafo or destino not in grafo:
            continue

        chave_geo  = f"{origem}-{destino}"
        pontos_geo = geometrias.get(chave_geo, [])

        if pontos_geo:
            orig_no  = grafo[origem]
            dest_no  = grafo[destino]
            seq_rad = (
                [(orig_no["lat"], orig_no["lon"])] +
                [(graus_para_radianos(p["lat"]), graus_para_radianos(p["lon"])) for p in pontos_geo] +
                [(dest_no["lat"], dest_no["lon"])]
            )
            distancia = calcular_distancia_segmentos(seq_rad)
            geometria_graus = (
                [[orig_no["lat_graus"], orig_no["lon_graus"]]] +
                [[p["lat"], p["lon"]] for p in pontos_geo] +
                [[dest_no["lat_graus"], dest_no["lon_graus"]]]
            )
        else:
            lat1 = grafo[origem]["lat"]
            lon1 = grafo[origem]["lon"]
            lat2 = grafo[destino]["lat"]
            lon2 = grafo[destino]["lon"]
            distancia = calcular_distancia_haversine(lat1, lon1, lat2, lon2)
            geometria_graus = []

        grafo[origem]["arestas"].append({
            "destino":         destino,
            "distancia":       distancia,
            "geometria_graus": geometria_graus,
            **{k: v for k, v in a.items() if k not in ("origem", "destino")}
        })

    return grafo

grafo = montar_grafo()

def calcular_peso_aresta(aresta, ctx):
    if ctx["chuva"] > aresta["chuva"]:
        return float("inf"), "bloqueado_chuva"
    if ctx["veiculo"] == 2 and aresta["veiculo"] == 0:
        return float("inf"), "bloqueado_veiculo"
    if ctx["hora"] in [1, 7] and aresta["comunidade"] == 1:
        return float("inf"), "bloqueado_comunidade"

    largura = obter_peso(PARAMS["largura"], aresta["largura"])
    fluxo   = obter_peso(PARAMS["fluxo"],   aresta["fluxo"])
    tipo    = obter_peso(PARAMS["tipo"],    aresta["tipo"])
    chuva   = obter_peso(PARAMS["chuva"],   ctx["chuva"])
    hora    = obter_peso(PARAMS["hora"],    ctx["hora"])
    distancia = aresta["distancia"]

    peso = distancia + (
        1 * largura + 2 * hora + 3 * tipo + 4 * fluxo + 5 * chuva
    ) / 15 * (largura / 10) * (tipo / 10) * (fluxo / 10)

    return peso, "ok"

def dijkstra(origem, destino, ctx):
    if origem not in grafo or destino not in grafo:
        return None

    distancias = {origem: 0}
    anteriores = {}
    fila = [(0, origem)]

    while fila:
        custo_atual, no_atual = heapq.heappop(fila)
        if no_atual == destino:
            break
        if custo_atual > distancias.get(no_atual, float("inf")):
            continue
        for aresta in grafo[no_atual]["arestas"]:
            vizinho = aresta["destino"]
            peso, _ = calcular_peso_aresta(aresta, ctx)
            if peso == float("inf"):
                continue
            novo_custo = custo_atual + peso
            if novo_custo < distancias.get(vizinho, float("inf")):
                distancias[vizinho] = novo_custo
                anteriores[vizinho] = no_atual
                heapq.heappush(fila, (novo_custo, vizinho))

    if destino not in anteriores:
        return None

    caminho = []
    atual = destino
    while atual in anteriores:
        caminho.append(atual)
        atual = anteriores[atual]
    caminho.append(origem)
    return caminho[::-1]

def montar_polyline_grafo(caminho):
    """Constrói polyline completa usando geometria real das arestas."""
    if not caminho or len(caminho) < 2:
        return []

    polyline = []
    for i in range(len(caminho) - 1):
        u = caminho[i]
        v = caminho[i + 1]
        aresta_uv = next(
            (a for a in grafo[u]["arestas"] if a["destino"] == v), None
        )

        if aresta_uv and aresta_uv.get("geometria_graus"):
            pontos = aresta_uv["geometria_graus"]
        else:
            pontos = [
                [math.degrees(grafo[u]["lat"]), math.degrees(grafo[u]["lon"])],
                [math.degrees(grafo[v]["lat"]), math.degrees(grafo[v]["lon"])]
            ]

        if i == 0:
            polyline.extend(pontos)
        else:
            polyline.extend(pontos[1:])  # evita duplicação de ponto

    return polyline

def buscar_rota_ors(caminho):
    if not caminho or len(caminho) < 2:
        return None
    rota = []
    for i in range(len(caminho) - 1):
        u = caminho[i]
        v = caminho[i + 1]
        coords = [
            [math.degrees(grafo[u]["lon"]), math.degrees(grafo[u]["lat"])],
            [math.degrees(grafo[v]["lon"]), math.degrees(grafo[v]["lat"])]
        ]
        try:
            response = req_lib.post(
                ORS_URL,
                json={"coordinates": coords},
                headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
                timeout=5
            )
            if response.status_code == 200:
                pontos = response.json()["features"][0]["geometry"]["coordinates"]
                rota.extend([[p[1], p[0]] for p in pontos])
        except Exception:
            continue
    return rota if rota else None

@app.route("/api/calcular", methods=["POST"])
def calcular_rota():
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"status": "erro", "mensagem": "Payload JSON inválido"}), 400

        origem  = int(dados["origem"])
        destino = int(dados["destino"])
        chuva   = int(dados["chuva"])
        veiculo = int(dados["veiculo"])
        hora_id = classificar_hora(dados["hora"])

        contexto = {"chuva": chuva, "veiculo": veiculo, "hora": hora_id}

        caminho = dijkstra(origem, destino, contexto)
        if not caminho:
            return jsonify({"status": "sem_rota"})

        # Polyline com geometria real das arestas (fallback para ORS se vazio)
        polyline = montar_polyline_grafo(caminho)
        if not polyline:
            polyline = buscar_rota_ors(caminho)

        return jsonify({"status": "ok", "caminho": caminho, "polyline": polyline})

    except KeyError as e:
        return jsonify({"status": "erro", "mensagem": f"Campo ausente: {e}"}), 400
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route("/api/pontos")
def listar_pontos():
    return jsonify(sorted(grafo.keys()))

@app.route("/api/nos")
def listar_nos():
    resultado = {}
    for id_no, dados in grafo.items():
        resultado[id_no] = {
            "nome": dados["nome"],
            "lat":  math.degrees(dados["lat"]),
            "lon":  math.degrees(dados["lon"]),
        }
    return jsonify(resultado)

@app.route("/api/geometria")
def listar_geometria():
    return jsonify(GRAFO_JSON.get("geometria", {}))

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/<path:filename>")
def arquivos_estaticos(filename):
    return send_from_directory(BASE_DIR, filename)

if __name__ == "__main__":
    print(f"\n  GPS Petropolis rodando em http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=True)