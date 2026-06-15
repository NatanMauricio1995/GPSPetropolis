import json
import os
import heapq
import math
import requests as req_lib
from flask import Flask, jsonify, request, send_from_directory

# =========================================================
# ── CONFIGURAÇÃO GLOBAL DO SERVIDOR
# =========================================================
# Centraliza constantes críticas do sistema
# Evita "magic numbers" espalhados no código

ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA2ZWE3NjcxYzY0MTRjMTZhZThmOWI4NTM5YTYwMjQ4IiwiaCI6Im11cm11cjY0In0="
ORS_URL     = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

PORT     = 5000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# =========================================================
# ── CAMADA DE DADOS (I/O)
# =========================================================
# Responsável exclusivamente por leitura de arquivos
# Princípio aplicado: Single Responsibility

def carregar_json(nome_arquivo: str) -> dict:
    """
    Lê arquivos JSON do disco com validação.

    Garante:
    - existência do arquivo
    - encoding correto (UTF-8)
    """
    caminho = os.path.join(BASE_DIR, nome_arquivo)

    if not os.path.exists(caminho):
        raise FileNotFoundError(f"Arquivo não encontrado: {nome_arquivo}")

    with open(caminho, encoding="utf-8") as f:
        return json.load(f)

# Dados carregados uma única vez (cache em memória)
GRAFO_JSON = carregar_json("nos_e_arestas.json")
PARAMS     = carregar_json("parametros.json")

# =========================================================
# ── CAMADA MATEMÁTICA
# =========================================================
# Isola cálculos geográficos e conversões

def graus_para_radianos(graus: float) -> float:
    """
    Conversão necessária para uso da fórmula de Haversine
    """
    return (graus * math.pi) / 180


def calcular_distancia_haversine(lat1, lon1, lat2, lon2) -> float:
    """
    Calcula distância geodésica entre dois pontos da Terra.

    IMPORTANTE:
    - Entrada deve estar em radianos
    - Retorno em metros

    Complexidade: O(1)
    """
    raio_terra = PARAMS["constantes"]["raio_terra_m"]

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2 +
        math.cos(lat1) * math.cos(lat2) *
        math.sin(delta_lon / 2) ** 2
    )

    return 2 * raio_terra * math.asin(math.sqrt(a))

# =========================================================
# ── CAMADA DE PARÂMETROS DINÂMICOS
# =========================================================
# Permite alterar comportamento do algoritmo SEM mexer no código

def obter_peso(lista: list, id_valor: int) -> float:
    """
    Busca peso configurável no JSON.

    Caso não encontre:
    - retorna fallback neutro (1.0)
    """
    for item in lista:
        if item["id"] == id_valor:
            return item["peso"]

    return 1.0


def classificar_hora(hora_str: str) -> int:
    """
    Converte horário real (HH:MM) para categoria discreta.

    Exemplo:
    07:30 → pico da manhã

    Isso permite:
    - simplificar lógica
    - reduzir complexidade no algoritmo
    """
    for faixa in PARAMS["hora"]:
        if faixa["inicio"] <= hora_str <= faixa["fim"]:
            return faixa["id"]

    return 4  # fallback neutro

# =========================================================
# ── CONSTRUÇÃO DO GRAFO
# =========================================================
# Transforma JSON em estrutura otimizada para Dijkstra

def montar_grafo() -> dict:
    """
    Estrutura final:
    {
        no: {
            lat,
            lon,
            arestas: [...]
        }
    }

    Otimizações:
    - coordenadas já convertidas para radianos
    - distância pré-calculada
    """
    grafo = {}

    # -------------------------
    # Inicialização dos nós
    # -------------------------
    for id_no, dados in GRAFO_JSON["nos"].items():
        grafo[int(id_no)] = {
            "lat": graus_para_radianos(dados["lat"]),
            "lon": graus_para_radianos(dados["lon"]),
            "arestas": []
        }

    # -------------------------
    # Criação das arestas
    # -------------------------
    for a in GRAFO_JSON["arestas"]:
        origem  = a["origem"]
        destino = a["destino"]

        lat1 = grafo[origem]["lat"]
        lon1 = grafo[origem]["lon"]
        lat2 = grafo[destino]["lat"]
        lon2 = grafo[destino]["lon"]

        distancia = calcular_distancia_haversine(lat1, lon1, lat2, lon2)

        grafo[origem]["arestas"].append({
            "destino": destino,
            "distancia": distancia,
            **a
        })

    return grafo

def obter_rota_real(coords):
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    body = {
        "coordinates": coords
    }

    response = req_lib.post(ORS_URL, json=body, headers=headers)

    if response.status_code != 200:
        print("Erro ORS:", response.text)
        return None

    return response.json()


# Grafo carregado uma vez (evita recomputação)
grafo = montar_grafo()

def caminho_para_coords(caminho):
    coords = []

    for no in caminho:
        lat = grafo[no]["lat"]
        lon = grafo[no]["lon"]

        lat = math.degrees(lat)
        lon = math.degrees(lon)

        coords.append([lon, lat])

    return coords

# =========================================================
# ── REGRAS DE NEGÓCIO (CUSTO DAS ARESTAS)
# =========================================================

def calcular_peso_aresta(aresta: dict, ctx: dict):
    """
    Calcula custo de uma aresta baseado em múltiplos fatores.

    Fatores considerados:
    - clima (chuva)
    - tipo de veículo
    - horário
    - características da via

    Estratégia:
    1. BLOQUEIO → retorna infinito
    2. PESO DINÂMICO → baseado em parâmetros
    3. FUNÇÃO DE CUSTO → combinação ponderada
    """

    # -------------------------
    # BLOQUEIOS (hard constraints)
    # -------------------------
    # aresta["chuva"] = 0 → via sem rio, sem restrição de chuva (nunca alaga)
    # aresta["chuva"] > 0 → nível máximo suportado; bloqueia se chuva atual SUPERA esse limite
    if aresta["chuva"] > 0 and ctx["chuva"] > aresta["chuva"]:
        return float("inf"), "bloqueado_chuva"

    if ctx["veiculo"] == 2 and aresta["veiculo"] == 0:
        return float("inf"), "bloqueado_veiculo"

    if ctx["hora"] in [1, 7] and aresta["comunidade"] == 1:
        return float("inf"), "bloqueado_comunidade"

    # -------------------------
    # PESOS DINÂMICOS
    # -------------------------
    largura = obter_peso(PARAMS["largura"], aresta["largura"])
    fluxo   = obter_peso(PARAMS["fluxo"],   aresta["fluxo"])
    tipo    = obter_peso(PARAMS["tipo"],    aresta["tipo"])
    chuva   = obter_peso(PARAMS["chuva"],   ctx["chuva"])
    hora    = obter_peso(PARAMS["hora"],    ctx["hora"])

    distancia = aresta["distancia"]

    # -------------------------
    # FUNÇÃO DE CUSTO FINAL
    # -------------------------
    peso = distancia + (
        1 * largura +
        2 * hora +
        3 * tipo +
        4 * fluxo +
        5 * chuva
    ) / 15 * (largura / 10) * (tipo / 10)

    return peso, "ok"

# =========================================================
# ── ALGORITMO DE DIJKSTRA
# =========================================================

def dijkstra(origem: int, destino: int, ctx: dict):
    """
    Implementação clássica com heap (fila de prioridade)

    Complexidade:
    O((V + E) log V)

    Otimizações:
    - early stop quando encontra destino
    
    Retorna: (caminho, custo_total, distancia_metros) ou None
    """

    distancias = {origem: 0}
    dist_metros = {origem: 0}   # distância geográfica acumulada (sem pesos)
    anteriores = {}
    fila = [(0, origem)]

    while fila:
        custo_atual, no_atual = heapq.heappop(fila)

        if no_atual == destino:
            break

        for aresta in grafo[no_atual]["arestas"]:
            vizinho = aresta["destino"]

            peso, _ = calcular_peso_aresta(aresta, ctx)

            if peso == float("inf"):
                continue

            novo_custo = custo_atual + peso

            if novo_custo < distancias.get(vizinho, float("inf")):
                distancias[vizinho] = novo_custo
                dist_metros[vizinho] = dist_metros.get(no_atual, 0) + aresta["distancia"]
                anteriores[vizinho] = no_atual
                heapq.heappush(fila, (novo_custo, vizinho))

    if destino not in anteriores:
        return None, 0, 0

    # Reconstrução do caminho
    caminho = []
    atual = destino

    while atual in anteriores:
        caminho.append(atual)
        atual = anteriores[atual]

    caminho.append(origem)
    return caminho[::-1], distancias.get(destino, 0), dist_metros.get(destino, 0)

# =========================================================
# ── INTEGRAÇÃO COM ORS (CORRIGIDO)
# =========================================================

def buscar_rota_ors(caminho):
    """
    Converte caminho em rota real (coordenadas contínuas).

    IMPORTANTE:
    - ORS espera graus (não radianos)
    - conversão feita aqui
    """

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
                headers={
                    "Authorization": ORS_API_KEY,
                    "Content-Type": "application/json"
                },
                timeout=5
            )

            if response.status_code == 200:
                pontos = response.json()["features"][0]["geometry"]["coordinates"]
                rota.extend([[p[1], p[0]] for p in pontos])

        except:
            continue

    return rota if rota else None

# =========================================================
# ── API
# =========================================================

@app.route("/api/calcular", methods=["POST"])
def calcular_rota():
    """
    Endpoint principal consumido pelo front-end
    """

    dados = request.get_json()

    origem  = int(dados["origem"])
    destino = int(dados["destino"])
    chuva   = int(dados["chuva"])
    veiculo = int(dados["veiculo"])
    hora_id = classificar_hora(dados["hora"])

    contexto = {
        "chuva": chuva,
        "veiculo": veiculo,
        "hora": hora_id
    }

    caminho, custo_total, dist_metros = dijkstra(origem, destino, contexto)

    if not caminho:
        return jsonify({"status": "sem_rota"})

    polyline = buscar_rota_ors(caminho)

    # Distância real: usa polyline ORS quando disponível, senão usa Haversine pelos nós
    dist_real = dist_metros
    if polyline and len(polyline) >= 2:
        dist_real = 0
        for i in range(len(polyline) - 1):
            lat1, lon1 = [x * math.pi / 180 for x in polyline[i]]
            lat2, lon2 = [x * math.pi / 180 for x in polyline[i + 1]]
            dLat = lat2 - lat1; dLon = lon2 - lon1
            a = math.sin(dLat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dLon/2)**2
            dist_real += 2 * 6371008.8 * math.asin(math.sqrt(a))

    return jsonify({
        "status": "ok",
        "caminho": caminho,
        "polyline": polyline,
        "custo": round(custo_total, 2),
        "distancia_m": round(dist_real, 1)
    })

@app.route("/api/pontos")
def listar_pontos():
    """
    Fornece nós para o front-end (select)
    """
    return jsonify(sorted(grafo.keys()))

# =========================================================
# ── FRONTEND
# =========================================================

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/<path:filename>")
def arquivos_estaticos(filename):
    return send_from_directory(BASE_DIR, filename)
    
# =========================================================
# ── EXECUÇÃO
# =========================================================
@app.route("/rota", methods=["POST"])
def rota():
    data = request.json

    origem = int(data["origem"])
    destino = int(data["destino"])

    ctx = {
        "chuva": data["chuva"],
        "hora": classificar_hora(data["hora"]),
        "veiculo": data["veiculo"]
    }

    caminho = dijkstra(origem, destino, ctx)

    if not caminho:
        return jsonify({"erro": "Rota não encontrada"}), 400

    coords = caminho_para_coords(caminho)

    coords_reduzidas = coords[::2]

    rota_real = obter_rota_real(coords_reduzidas)

    if rota_real:
        return jsonify({
            "tipo": "ors",
            "geojson": rota_real
        })

    return jsonify({
        "tipo": "simples",
        "coords": coords
    })
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)