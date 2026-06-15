# Descrição do Documento – Estrutura de Nós e Arestas

O arquivo JSON representa um grafo direcionado e ponderado da cidade de Petrópolis, utilizado para simulação de rotas inteligentes considerando múltiplos fatores urbanos e ambientais.

## 🔷 Estrutura Geral
O documento é dividido em duas partes principais:
* **"nos"**: Conjunto de vértices do grafo (pontos geográficos).
* **"arestas"**: Conexões entre os vértices.

## 📍 Nós (Vértices)
Cada nó representa um ponto geográfico real e contém:
* **nome**: Descrição do local.
* **lat**: Latitude em graus decimais.
* **lon**: Longitude em graus decimais.

> **Nota Técnica:** Embora o JSON armazene em graus decimais, o sistema utiliza esses dados para cálculos de distância real (Haversine), integrando-se facilmente com Leaflet ou Google Maps.

## 🔗 Arestas (Conexões)
As arestas possuem atributos que influenciam o custo da rota:
* **origem/destino**: IDs de referência dos nós.
* **rio**: Proximidade de rios (0 ou 1).
* **chuva**: Nível de impacto climático (0 a 6).
* **veiculo**: Permissão para veículos de grande porte/caminhão (0 ou 1).
* **largura**: Classificação da largura da via (1 a 3).
* **fluxo**: Intensidade de tráfego (1 a 5).
* **tipo**: Classificação da via (1 a 3).
* **comunidade**: Área sensível ou de risco (0 ou 1).

## 🧠 Interpretação e Aplicações
O sistema permite otimizar rotas para evitar áreas com risco de enchente (rio + chuva), minimizar trânsito (fluxo) e respeitar restrições logísticas (veiculo + largura).