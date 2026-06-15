# README — Sistema de Parâmetros de Roteamento

Este arquivo define a inteligência por trás do cálculo de rotas, atribuindo pesos dinâmicos conforme condições reais.

## 1. CONSTANTES e FÓRMULAS
* raio_terra_m: Utilizado na fórmula de Haversine para converter coordenadas em distância métrica.
* Fórmula de Peso: 
  "peso = distancia * (1 * largura + 2 * hora + 3 * tipo + 4 * fluxo + 5 * chuva) / 10 * (largura / 10) * (tipo / 10) * (fluxo / 10)"
  A fórmula prioriza a segurança e o fluxo, onde o impacto da chuva e do tráfego tem peso maior no custo final.
* Fórmula da distância:
  "d = 2r * arcsin( √[ sin²(Δφ/2) + cos(φ1) * cos(φ2) * sin²(Δλ/2)])"
	
## 2. TABELA DE FATORES (Pesos)

|  Fator  |            Níveis            | Impacto 						 |
| ------- | ---------------------------- | ----------------------------------------------------- |
| Chuva   | 0 (Sem) a 6 (Extrema) 	 | Aumenta o custo conforme a intensidade. 		 |
| Fluxo   | 1 (Mto Baixo) a 5 (Mto Alto) | Representa o tráfego em tempo real. 			 |
| Largura | 1 (Estreita) a 3 (Larga) 	 | Vias largas reduzem o peso (0.5), facilitando a rota. |
| Hora    | 7 faixas horárias 		 | Define horários de pico (Pico Noite = peso 2.0).	 |

## 3. LÓGICA BINÁRIA (0 e 1)
Aplicada aos campos:
* rio: Se 1 e chuva > 3, o custo de deslocamento sobe exponencialmente para evitar alagamentos.
* veiculo: Define se a via comporta veículos de carga.
* comunidade: Identifica áreas de atenção social ou velocidade reduzida.

## 📐 Importante
Os valores de ID nas arestas (ex: "fluxo: 4") devem obrigatoriamente existir na tabela de parâmetros para que o cálculo seja válido.