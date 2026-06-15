import json
import os
import heapq
import math
import requests as req_lib
from flask import Flask, jsonify, request, send_from_directory

# =========================================================
# ── CONFIGURAÇÃO GLOBAL DO SERVIDOR
# =========================================================
# Centraliza constantes críticas do sistema.
# Evita "magic numbers" espalhados no código.

ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA2ZWE3NjcxYzY0MTRjMTZhZThmOWI4NTM5YTYwMjQ4IiwiaCI6Im11cm11cjY0In0="
ORS_URL     = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

PORT     = 5000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# =========================================================
# ── CAMADA DE DADOS (I/O)
# =========================================================
# Responsável exclusivamente por leitura de arquivos.
# Princípio aplicado: Single Responsibility.

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
# Isola cálculos geográficos e conversões.

def graus_para_radianos(graus: float) -> float:
    """
    Conversão necessária para uso da fórmula de Haversine.
    Os nós são armazenados em graus decimais no JSON,
    mas Haversine exige radianos.
    """
    return (graus * math.pi) / 180


def calcular_distancia_haversine(lat1, lon1, lat2, lon2) -> float:
    """
    Calcula distância geodésica entre dois pontos da Terra.

    IMPORTANTE:
    - Entrada deve estar em radianos
    - Retorno em metros

    Fórmula: d = 2r * arcsin(√[sin²(Δφ/2) + cos(φ1)·cos(φ2)·sin²(Δλ/2)])
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
# Permite alterar comportamento do algoritmo SEM mexer no código.
# Os pesos são lidos do parametros.json, tornando o sistema
# configurável sem redeploy.

def obter_peso(lista: list, id_valor: int) -> float:
    """
    Busca peso configurável no JSON pelo campo "id".

    Caso não encontre:
    - retorna fallback neutro (1.0) para não distorcer o custo
    """
    for item in lista:
        if item["id"] == id_valor:
            return item["peso"]

    return 1.0


def classificar_hora(hora_str: str) -> int:
    """
    Converte horário real (HH:MM) para categoria discreta.

    Exemplo:
    "07:30" → id 2 (Pico da manhã, peso 1.8)
    "22:00" → id 7 (Noite, peso 1.0)

    Permite simplificar a lógica: o Dijkstra trabalha com
    IDs inteiros em vez de strings de tempo.
    Fallback id=4 corresponde a "Tarde" (peso neutro 1.3).
    """
    for faixa in PARAMS["hora"]:
        if faixa["inicio"] <= hora_str <= faixa["fim"]:
            return faixa["id"]

    return 4  # fallback: Tarde

# =========================================================
# ── CONSTRUÇÃO DO GRAFO
# =========================================================
# Transforma o JSON em estrutura otimizada para Dijkstra.

def montar_grafo() -> dict:
    """
    Estrutura final do grafo:
    {
        id_no (int): {
            "lat":    float (radianos),
            "lon":    float (radianos),
            "arestas": [ { destino, distancia, rio, chuva, ... } ]
        }
    }

    Otimizações aplicadas:
    - Coordenadas pré-convertidas para radianos (evita conversão repetida)
    - Distância Haversine pré-calculada por aresta (evita recálculo no Dijkstra)
    - IDs dos nós convertidos de string para int (chave dict mais eficiente)

    Complexidade: O(N + E), N=nós, E=arestas
    """
    grafo = {}

    # ── Inicialização dos nós ────────────────────────────
    for id_no, dados in GRAFO_JSON["nos"].items():
        grafo[int(id_no)] = {
            "lat":    graus_para_radianos(dados["lat"]),
            "lon":    graus_para_radianos(dados["lon"]),
            "arestas": []
        }

    # ── Criação das arestas com distância pré-calculada ──
    for a in GRAFO_JSON["arestas"]:
        origem  = a["origem"]
        destino = a["destino"]

        lat1 = grafo[origem]["lat"]
        lon1 = grafo[origem]["lon"]
        lat2 = grafo[destino]["lat"]
        lon2 = grafo[destino]["lon"]

        distancia = calcular_distancia_haversine(lat1, lon1, lat2, lon2)

        grafo[origem]["arestas"].append({
            "destino":   destino,
            "distancia": distancia,
            **a           # expande todos os atributos originais da aresta
        })

    return grafo


# Grafo carregado uma vez na inicialização (evita recomputação por request)
grafo = montar_grafo()

# =========================================================
# ── REGRAS DE NEGÓCIO (CUSTO DAS ARESTAS)
# =========================================================

def calcular_peso_aresta(aresta: dict, ctx: dict):
    """
    Calcula o custo de traversal de uma aresta dado o contexto atual.

    Parâmetros:
    - aresta : dict com atributos da via (rio, chuva, veiculo, largura, fluxo, tipo, comunidade)
    - ctx    : dict com condições da viagem (chuva, veiculo, hora)

    Retorno: (peso: float, motivo: str)
    - peso = inf → aresta bloqueada (não usável pelo Dijkstra)
    - peso > 0   → custo de travessia

    Estratégia em 3 camadas:
    1. BLOQUEIOS (hard constraints) — retornam infinito imediatamente
    2. PESOS DINÂMICOS — lidos do parametros.json
    3. FUNÇÃO DE CUSTO — combinação ponderada dos fatores

    ── CORREÇÃO PRINCIPAL — Condição de chuva ──────────────
    BUG ORIGINAL: ctx["chuva"] >= aresta["chuva"]
      - aresta["chuva"] representa o nível MÁXIMO de chuva
        que a via suporta sem ser bloqueada.
      - Com ">=", quando ctx["chuva"]=0 e aresta["chuva"]=0
        (via sem influência de rio, arestas mais comuns),
        a condição 0 >= 0 era True → aresta bloqueada.
      - Efeito: 93 das 216 arestas (43%) permanentemente
        inacessíveis, impedindo rotas mesmo sem chuva alguma.

    CORREÇÃO: ctx["chuva"] > aresta["chuva"]
      - Só bloqueia quando a chuva ATUAL SUPERA o limite.
      - aresta chuva=0 + ctx chuva=0 → liberada ✓
      - aresta chuva=3 + ctx chuva=4 → bloqueada ✓
      - aresta chuva=0 + ctx chuva=1 → bloqueada ✓ (via vulnerável)
    """

    # ── BLOQUEIOS (hard constraints) ──────────────────────
    # Cada condição representa uma restrição absoluta.
    # A ordem importa: verificações mais baratas primeiro.

    # Via vulnerável: chuva atual supera o limite da via
    if ctx["chuva"] > aresta["chuva"]:          # CORRIGIDO: > em vez de >=
        return float("inf"), "bloqueado_chuva"

    # Restrição de veículo: caminhão (2) em via que não suporta (veiculo=0)
    if ctx["veiculo"] == 2 and aresta["veiculo"] == 0:
        return float("inf"), "bloqueado_veiculo"

    # Restrição horária: comunidades bloqueadas de madrugada (id=1) e à noite (id=7)
    # Evita rotas por áreas sensíveis em horários de menor segurança
    if ctx["hora"] in [1, 7] and aresta["comunidade"] == 1:
        return float("inf"), "bloqueado_comunidade"

    # ── PESOS DINÂMICOS ───────────────────────────────────
    # Lidos do parametros.json — configuráveis sem alterar código
    largura = obter_peso(PARAMS["largura"], aresta["largura"])
    fluxo   = obter_peso(PARAMS["fluxo"],   aresta["fluxo"])
    tipo    = obter_peso(PARAMS["tipo"],    aresta["tipo"])
    chuva   = obter_peso(PARAMS["chuva"],   ctx["chuva"])
    hora    = obter_peso(PARAMS["hora"],    ctx["hora"])

    distancia = aresta["distancia"]

    # ── FUNÇÃO DE CUSTO ───────────────────────────────────
    # Pesos relativos dos fatores (maior = mais impacto no custo):
    #   1× largura  — via larga reduz custo (peso 0.5), estreita aumenta (1.5)
    #   2× hora     — horários de pico dobram o impacto do tráfego
    #   3× tipo     — tipo de via afeta a velocidade média
    #   4× fluxo    — volume de tráfego em tempo real
    #   5× chuva    — maior fator: prioriza segurança climática
    #
    # Divisão por 15 normaliza a soma ponderada.
    # Multiplicadores finais (largura/10, tipo/10, fluxo/10):
    #   amplificam o custo em vias estreitas, lentas e congestionadas.
    peso = distancia * (
        1 * largura +
        2 * hora    +
        3 * tipo    +
        4 * fluxo   +
        5 * chuva
    ) / 15 * (largura / 10) * (tipo / 10) * (fluxo / 10)

    return peso, "ok"

# =========================================================
# ── ALGORITMO DE DIJKSTRA
# =========================================================

def dijkstra(origem: int, destino: int, ctx: dict):
    """
    Encontra o caminho de menor custo entre dois nós do grafo.

    Implementação: heap mínimo (fila de prioridade)
    Complexidade: O((V + E) log V)

    Otimizações:
    - Early stop: interrompe ao atingir o destino
    - Lazy deletion: ignora entradas obsoletas do heap
      (técnica comum para evitar remoção custosa de O(log n))

    Retorno:
    - Lista de IDs dos nós no caminho (origem → destino)
    - None se não houver caminho acessível
    """

    # Valida se os nós existem no grafo antes de iniciar
    if origem not in grafo or destino not in grafo:
        return None

    distancias = {origem: 0}    # custo acumulado mínimo por nó
    anteriores = {}              # predecessor no caminho ótimo
    fila = [(0, origem)]         # (custo, no) — heap mínimo

    while fila:
        custo_atual, no_atual = heapq.heappop(fila)

        # Early stop: destino alcançado com custo mínimo garantido
        if no_atual == destino:
            break

        # Lazy deletion: descarta entrada obsoleta do heap
        # Ocorre quando um nó foi relaxado após ser inserido na fila
        if custo_atual > distancias.get(no_atual, float("inf")):
            continue

        for aresta in grafo[no_atual]["arestas"]:
            vizinho = aresta["destino"]

            peso, _ = calcular_peso_aresta(aresta, ctx)

            if peso == float("inf"):
                continue  # aresta bloqueada — ignora

            novo_custo = custo_atual + peso

            # Relaxamento: atualiza se encontrou caminho mais barato
            if novo_custo < distancias.get(vizinho, float("inf")):
                distancias[vizinho] = novo_custo
                anteriores[vizinho] = no_atual
                heapq.heappush(fila, (novo_custo, vizinho))

    # Destino nunca foi alcançado (grafo desconexo nas condições atuais)
    if destino not in anteriores:
        return None

    # ── Reconstrução do caminho ───────────────────────────
    # Percorre "anteriores" de trás para frente (destino → origem)
    # e inverte para obter a sequência correta.
    caminho = []
    atual = destino

    while atual in anteriores:
        caminho.append(atual)
        atual = anteriores[atual]

    caminho.append(origem)
    return caminho[::-1]

# =========================================================
# ── INTEGRAÇÃO COM ORS
# =========================================================

def buscar_rota_ors(caminho: list):
    """
    Enriquece o caminho do grafo com polyline real via OpenRouteService.

    Por que necessário:
    - O grafo é esparso (nós em pontos de interesse, não cada esquina)
    - ORS interpola as ruas reais entre dois pontos consecutivos
    - Resultado: rota exibível no mapa com traçado fiel às vias

    IMPORTANTE:
    - ORS espera coordenadas em graus decimais (não radianos)
    - Os nós do grafo estão em radianos → conversão obrigatória aqui
    - Chamadas feitas segmento a segmento (u → v) para maior precisão

    Fallback:
    - Retorna None se ORS estiver indisponível ou a chave expirar
    - O frontend detecta None e desenha linha reta pelos nós do grafo
    """
    if not caminho or len(caminho) < 2:
        return None

    rota = []

    for i in range(len(caminho) - 1):
        u = caminho[i]
        v = caminho[i + 1]

        # Converte radianos → graus para o ORS
        # ORS usa formato [longitude, latitude] (GeoJSON padrão)
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
                # ORS retorna [lon, lat] → inverte para [lat, lon] (padrão Leaflet)
                pontos = response.json()["features"][0]["geometry"]["coordinates"]
                rota.extend([[p[1], p[0]] for p in pontos])

        except Exception:
            continue  # falha silenciosa por segmento — tenta o próximo

    return rota if rota else None

# =========================================================
# ── API
# =========================================================

@app.route("/api/calcular", methods=["POST"])
def calcular_rota():
    """
    Endpoint principal — calcula rota com Dijkstra e retorna polyline.

    Payload esperado (JSON):
    {
        "origem":  int,    — ID do nó de origem
        "destino": int,    — ID do nó de destino
        "hora":    "HH:MM" — horário de saída
        "chuva":   int,    — ID do nível de chuva (0–6, conforme parametros.json)
        "veiculo": int,    — 1=Automóvel, 2=Caminhão
    }

    Retornos possíveis:
    - { status: "ok",       caminho: [...], polyline: [...] ou null }
    - { status: "sem_rota" }
    - { status: "erro",     mensagem: "..." }
    """
    try:
        dados = request.get_json()

        if not dados:
            return jsonify({"status": "erro", "mensagem": "Payload JSON inválido"}), 400

        origem  = int(dados["origem"])
        destino = int(dados["destino"])
        chuva   = int(dados["chuva"])
        veiculo = int(dados["veiculo"])
        hora_id = classificar_hora(dados["hora"])

        contexto = {
            "chuva":   chuva,
            "veiculo": veiculo,
            "hora":    hora_id
        }

        caminho = dijkstra(origem, destino, contexto)

        if not caminho:
            return jsonify({"status": "sem_rota"})

        # Tenta enriquecer com polyline real via ORS
        # polyline=None é aceito — frontend usa fallback pelos nós
        polyline = buscar_rota_ors(caminho)

        return jsonify({
            "status":   "ok",
            "caminho":  caminho,
            "polyline": polyline
        })

    except KeyError as e:
        return jsonify({"status": "erro", "mensagem": f"Campo ausente: {e}"}), 400
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route("/api/pontos")
def listar_pontos():
    """
    Lista os IDs de todos os nós do grafo em ordem crescente.
    Consumido pelo frontend para popular os selects de origem/destino.
    """
    return jsonify(sorted(grafo.keys()))


# =========================================================
# ── FRONTEND
# =========================================================

@app.route("/")
def index():
    """Serve o arquivo HTML principal."""
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def arquivos_estaticos(filename):
    """
    Serve todos os arquivos estáticos do diretório base:
    leaflet.js, leaflet.css, nos_e_arestas.json, parametros.json, etc.

    O frontend lê nos_e_arestas.json diretamente via fetch("/nos_e_arestas.json")
    para montar o cache local do grafo e desenhar nós/arestas no mapa.
    """
    return send_from_directory(BASE_DIR, filename)


# =========================================================
# ── EXECUÇÃO
# =========================================================

if __name__ == "__main__":
    print(f"\n  GPS Petropolis rodando em http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=True)