# MTR Monitor

> [Read this in English](./README.md)

Este repositório contém um script em Shell que **monitora** a conectividade de um host usando o [mtr (My Traceroute)](https://github.com/traviscross/mtr) e registra os resultados em um banco de dados [SQLite](https://www.sqlite.org/index.html). É ideal para verificar a **qualidade** da conexão com a internet em intervalos de tempo e **armazenar** o histórico de forma simples.

## Índice

1. [Recursos Principais](#recursos-principais)
2. [Requisitos](#requisitos)
3. [Instalação](#instalação)
4. [Uso](#uso)
5. [Importando Dados no SQLite](#importando-dados-no-sqlite)
6. [Dashboard](#dashboard)
7. [Agendamento com Crontab](#agendamento-com-crontab)
8. [Customizações](#customizações)
9. [Licença](#licença)

---

## Recursos Principais

- Executa o `mtr` de forma não interativa e salva a saída em **CSV**.
- Armazena os resultados em `mtr_data.db` (banco **SQLite**).
- Cria logs separados por **hostname** e com **timestamp** (data/hora) no nome do arquivo.
- É simples de configurar e estender para outros objetivos de monitoramento.

---

## Requisitos

- **Linux** (testado em distribuições como Ubuntu, Debian e similares)
- **mtr** instalado (>= 0.85 preferencialmente)
- **SQLite3** instalado (>= 3.0)

O script verifica se o `mtr` e o `sqlite3` estão instalados. Caso não estejam, ele avisa e encerra.

---

## Instalação

1. **Clone** este repositório:
   ```bash
   git clone https://github.com/rcarvalhoxavier/mtr-log.git
   cd mtr-log
   ```
2. **(Opcional) Torne o script executável**:
   ```bash
   chmod +x monitor.sh
   ```
3. **Instale** as dependências (se ainda não o fez):
   - **Ubuntu/Debian**:
     ```bash
     sudo apt-get update
     sudo apt-get install mtr sqlite3
     ```
   - **Fedora/CentOS**:
     ```bash
     sudo dnf install mtr sqlite
     ```
   - Ou [instale manualmente o sqlite3](https://www.sqlite.org/download.html) se precisar de versão diferente.

---

## Uso

Para executar manualmente:

```bash
./monitor.sh
```

O que acontece nesse script:

1. **Verifica** se o MTR e o SQLite3 estão instalados.
2. **Cria** (se não existir) o banco `mtr_data.db` e a tabela `mtr_data`.
3. **Executa** o MTR contra um alvo (por padrão `8.8.8.8`) e gera um arquivo CSV com data/hora no nome.
4. **Importa** esse CSV para o banco de dados `mtr_data.db`.

### Estrutura dos arquivos gerados

- **logs/SEU_HOSTNAME**: diretório criado para cada máquina (onde `hostname` retorna `SEU_HOSTNAME`).
  - Dentro dele, serão criados arquivos CSV no formato `YYYYMMDD_HHMMSS-mtr.csv`, por exemplo:
    ```
    logs/maquina01/20250124_135500-mtr.csv
    logs/maquina01/20250124_140000-mtr.csv
    ...
    ```
- **mtr_data.db**: banco de dados SQLite contendo a tabela `mtr_data`. Por padrão, o script cria colunas compatíveis com o CSV **padrão** do `mtr -C`.

#### Colunas (Exemplo de Layout)

Algumas colunas típicas que podem aparecer no CSV do MTR são:

1. **Mtr_Version:** –  Versão do MTR que gerou o registro.
2. **Start_Time:** –  Momento em que o teste foi iniciado, geralmente representado em Unix Epoch (segundos desde 1970-01-01) ou outro formato textual.
3. **Status:** –  Indica o estado do teste ou resultado, podendo ser “OK” ou outro código.
4. **Host** – Host ou IP de destino do hop.
5. **Hop:** – Número do salto (hop) na rota até o destino. Inicia em 1, 2, etc. Exemplo de valor: 1 (gateway local).
6. **Loss%** – Porcentagem de pacotes perdidos.
7. **Snt** – Número de pacotes enviados.
8. **Drops** – Contador de pacotes perdidos. No CSV bruto do MTR essa coluna **não tem nome no cabeçalho** (um campo em branco entre `Snt` e `Last`); versões anteriores deste README nem chegavam a documentá-la. Na tabela tipada `mtr_data` (ver `scripts/schema.sql`) ela é armazenada como a coluna `drops`.
9. **Last** – Latência do último pacote (ms).
10. **Avg** – Latência média (ms).
11. **Best** – Melhor (menor) latência (ms).
12. **Wrst** – Pior (maior) latência (ms).
13. **StDev** – Desvio padrão (ms).

Se o seu MTR gerar colunas adicionais (por exemplo `Mtr_Version`, `Start_Time`, `Status`, `Hop`, etc.), ajuste a definição do schema em `scripts/schema.sql` conforme necessário — esse arquivo é a fonte única da estrutura do banco, aplicada tanto por `monitor.sh` quanto por `scripts/migrate.sh`.

---

## Importando Dados no SQLite

Caso queira **verificar** os dados armazenados no banco:

```bash
sqlite3 mtr_data.db

-- Exemplo de consulta:
SELECT * FROM mtr_data LIMIT 10;
```

Isso listará as 10 primeiras entradas. Você também pode usar ferramentas como [DB Browser for SQLite](https://sqlitebrowser.org/) para visualização mais amigável.

---

## Dashboard

Gere um relatório estático em HTML a partir dos dados coletados com:

```bash
python3 scripts/dashboard.py
```

Isso grava `dashboard.html` na raiz do repositório. Não há dependências além da biblioteca padrão do Python 3.12 — nenhum pacote para instalar, e nenhum recurso externo: o arquivo é autocontido (sem referências `http`/`https`, sem `<script>`, sem `@import`) e pode ser aberto diretamente no navegador ou compartilhado como está.

O relatório tem três painéis, cada um respondendo a uma pergunta:

1. **De quem é a culpa** – A degradação nasce na minha rede ou fora dela?
2. **Está pior que o normal** – O período recente está pior que a linha de base histórica?
3. **A rota está instável** – O caminho até o destino está mudando ou quebrando?

**Uma nota sobre perda de pacotes:** perda registrada num hop intermediário que **não** se propaga até o hop de destino é um artefato de ICMP — muitos roteadores despriorizam ou limitam suas próprias respostas ICMP de TTL excedido, o que aparece como "perda" naquele hop sem nenhum impacto real na conectividade. O dashboard (e a view `v_loss` por trás dele) reporta isso explicitamente como **artefato**, separado da perda **real** (quando o próprio hop de destino apresenta perda). Só a perda real é contabilizada como degradação.

**Migrando bancos criados antes desta versão:** arquivos `mtr_data.db` criados antes da introdução do schema tipado usam um layout legado com todas as colunas em `TEXT`. Atualize-os com:

```bash
bash scripts/migrate.sh
```

O script é idempotente (rodá-lo novamente num banco já migrado não faz nada) e sempre cria um backup com timestamp (`mtr_data.db.bak-YYYYMMDD_HHMMSS`) antes de alterar qualquer coisa.

---

## Agendamento com Crontab

Para executar automaticamente a cada 5 minutos:

1. Edite o **crontab** do usuário desejado:
   ```bash
   crontab -e
   ```
2. Adicione uma linha (ajustando o caminho completo do script):
   ```bash
   */5 * * * * /home/usuario/mtr-log/monitor.sh
   ```
3. Salve o arquivo. O script será executado a cada 5 minutos, gerando um novo CSV (com data/hora no nome) e importando para `mtr_data.db`.

> **Observação**: Quando executado via cron, o diretório de trabalho pode ser diferente. No script, usamos `SCRIPT_DIR="$(dirname "$(realpath "$0")")"` para garantir que os arquivos de log e o banco sejam criados no local do script.

> **Observação para testes e experimentos**: o `monitor.sh` grava em `$MTR_DB` quando essa variável está definida, e cai no banco ao lado do script quando não está. Sempre exporte `MTR_DB` apontando para um arquivo descartável antes de dar `source` no script — rodar a suíte de testes ou um import manual contra o `mtr_data.db` de verdade injeta linhas fabricadas num banco que o cron alimenta a cada 5 minutos.

---

## Customizações

- **Alterar o alvo**: No script `monitor.sh`, procure pela variável `ALVO="8.8.8.8"` e mude para o IP ou hostname que deseja monitorar.
- **Quantidade de pacotes (ciclos)**: Ajuste a opção `-c 5` para outro valor (ex.: `-c 10`) se quiser mais amostragens por execução.
- **Estrutura da Tabela**: Se quiser armazenar mais dados (timestamp, hop, IP, etc.), edite a função que cria a tabela e ajuste o CSV gerado (pode usar `-o "col1 col2..."` no MTR ou usar um MTR custom).
- **Rodar em IPv6**: Acrescente `-6` no comando do MTR, se seu sistema tiver IPv6 configurado.

---

## Licença

Este projeto está licenciado sob a [MIT License](LICENSE). Fique à vontade para usá-lo, modificá-lo e distribuí-lo conforme suas necessidades.

---

**Dúvidas ou sugestões?**
Crie uma [issue](https://github.com/rcarvalhoxavier/mtr-log/issues) neste repositório ou envie um Pull Request!