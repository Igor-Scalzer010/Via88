# Qualidade e rastreabilidade dos dados

## Validação de 9 de novembro de 2026

O snapshot `antt_20261109T200022_cef724e4` foi construído a partir de 44 CSVs
(134.674.481 bytes originais), com 41 recursos ativos após reconciliar famílias de
concessões. O banco contém **1.014.297 registros** depois da remoção de duas
duplicatas completas, sem rejeições de data. Esses números descrevem esta versão
da fonte; não são constantes esperadas para futuras atualizações.

Os arquivos originais estão preservados por hash SHA-256. O manifesto de cada
snapshot registra suas versões, famílias, atividade e indicadores de qualidade.

## CSVs e verificação de integridade

Os arquivos observados usam Windows-1252 e ponto e vírgula, com variações nas aspas.
A autodetecção do DuckDB pode conservar aspas nos valores ou rejeitar um dialeto
que o parser CSV do Python consegue interpretar. O pipeline, por isso:

1. Preserva os bytes originais.
2. Usa o parser CSV do Python e valida a quantidade de campos de todas as linhas.
3. Produz um intermediário UTF-8 com escape e aspas uniformes.
4. Lê esse intermediário no DuckDB sem autodetecção, com tipos VARCHAR explícitos.
5. Confere quantidade de linhas, valores de amostras e datas válidas contra a
   leitura independente antes de publicar o snapshot.

Falhas deixam o ponteiro ativo anterior intacto. Valores originalmente inválidos
continuam rastreáveis; a verificação não os corrige por suposição nem os substitui
por zero.

## Recursos sucessores

Três famílias têm arquivos antigos e sucessores que abrangem o histórico com
correções. O sucessor conhecido tem prioridade, independentemente de uma renovação
da data de modificação do recurso antigo:

| Família | Antigo | Sucessor |
| --- | --- | --- |
| Capixaba | ECO101 | ECOVIAS CAPIXABA |
| Via Mineira | VIA MINEIRA | EPR VIA MINEIRA |
| Paraná | PRVIAS | MOTIVA PARANA |

Concatenar todos esses arquivos, ou deduplicá-los apenas por hash da linha, mantém
versões corrigidas em duplicidade. A seleção ocorre antes da consolidação.

## Duplicatas e identidade

O identificador de ocorrência é local à concessionária. Colisões desse identificador
e da data não comprovam que os registros representam o mesmo acidente. Registros
com campos divergentes são preservados e sinalizados, permitindo inspeção por
recurso e linha de origem.

A auditoria preliminar estimou 1.014.295 registros ao comparar apenas os 23 campos
comuns ao dicionário. A leitura completa encontrou dois pares adicionais da MOTIVA
MINAS SP em 15/11/2025, BR-381/MG, que diferem em `tipo_de_pista`:

- Ocorrência 132, km 500,729: Principal e Marginal.
- Ocorrência 241, km 489,309: Principal e Marginal.

Essas variantes permanecem no banco. As duas duplicatas completas removidas são
da ECOVIAS CAPIXABA e CONCEBRA. As métricas descrevem registros reportados; não
certificam uma identidade física global de cada acidente.

## Cobertura, gravidade e localização

A modificação do catálogo não informa até quando uma concessionária reportou
acidentes. A aplicação calcula datas e meses observados e apresenta limitações no
recorte consultado. Ausência de registros não comprova que nenhum acidente ocorreu.

Acidentes com vítimas graves contam registros com contagem positiva de feridos
graves; vítimas graves somam pessoas. Se todos os valores necessários forem
desconhecidos, a métrica fica desconhecida. Resultados parciais incluem aviso.

Há registros com `trecho` sem rodovia/UF, como “Alça Sul”. Eles permanecem nos
totais e nos detalhes, mas não entram em mapas ou rankings espaciais que exijam
essa informação. Faixas de 10 km também exigem km válido. A aplicação informa
quantos registros foram excluídos da agregação espacial.

O mapa usa limites estaduais do IBGE; não representa pontos de acidentes.
