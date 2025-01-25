# MTR Monitor

Este repositório contém um script em Shell que **monitora** a conectividade de um host usando o [mtr (My Traceroute)](https://github.com/traviscross/mtr) e registra os resultados em um banco de dados [SQLite](https://www.sqlite.org/index.html). É ideal para verificar a **qualidade** da conexão com a internet em intervalos de tempo e **armazenar** o histórico de forma simples.

## Índice

1. [Recursos Principais](#recursos-principais)
2. [Requisitos](#requisitos)
3. [Instalação](#instala%C3%A7%C3%A3o)
4. [Uso](#uso)
5. [Importando Dados no SQLite](#importando-dados-no-sqlite)
6. [Agendamento com Crontab](#agendamento-com-crontab)
7. [Customizações](#customiza%C3%A7%C3%B5es)
8. [Licença](#licen%C3%A7a)


## Recursos Principais

* Executa o `mtr` de forma não interativa e salva a saída em **CSV**.
* Armazena os resultados no arquivo `mtr_data.db` (banco **SQLite**).
* Cria logs separados por **hostname** e com **timestamp** (data/hora no nome do arquivo).
* É simples de configurar e estender para outros objetivos.


## Requisitos

* **Linux** (testado em distribuições como Ubuntu, Debian e similares)
* **mtr** instalado (>= 0.85 preferencialmente)
* **SQLite3** instalado (>= 3.0)

O script verifica se o `mtr` e `sqlite3` estão instalados. Caso não estejam, ele avisa e encerra.


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
   * Ubuntu/Debian:
     ```bash
     sudo apt-get update
     sudo apt-get install mtr sqlite3
     ```
   * Fedora/CentOS:
     ```bash
     sudo dnf install mtr sqlite
     ```
   * Ou [instale manualmente o sqlite3](https://www.sqlite.org/download.html) se precisar de versão diferente.


## Uso

Execute o script principal:

```bash
./monitor.sh
```

O fluxo será:
1. **Verificar** se o MTR e o SQLite3 estão instalados.
2. **Criar** (se não existir) o banco `mtr_data.db` e a tabela `mtr_data`.
3. **Executar** o MTR contra um alvo (por padrão `8.8.8.8`) e gerar um arquivo CSV com timestamp no nome.
4. **Importar** esse CSV no banco de dados `mtr_data.db`.

### Estrutura dos arquivos gerados

* **logs/SEU_HOSTNAME**: diretório criado para cada máquina (onde `hostname` retorna `SEU_HOSTNAME`).
  * Dentro dele, serão criados arquivos CSV no formato `YYYYMMDD_HHMMSS-mtr.csv`, por exemplo:
    ```
    logs/maquina01/20250124_135500-mtr.csv
    logs/maquina01/20250124_140000-mtr.csv
    ...
    ```
* **mtr_data.db**: banco de dados SQLite com a tabela `mtr_data`, criada por padrão com colunas compatíveis com a saída CSV padrão do MTR.

 1. **Mtr_Version:** Versão do MTR que gerou o registro. Exemplo de valor: MTR.0.95.
 2. **Start_Time:** Momento em que o teste foi iniciado, geralmente representado em Unix Epoch (segundos desde 1970-01-01) ou outro formato textual. Exemplo de valor: 1737689464 (equivalente a uma data/hora específica em UTC).
 3. **Status:** Indica o estado do teste ou resultado, podendo ser “OK” ou outro código.
 4. **Host:** Host (ou IP) de destino que está sendo testado pelo MTR. Exemplo de valor: 1.1.1.1 ou google.com.
 5. **Hop:** Número do salto (hop) na rota até o destino. Inicia em 1, 2, etc. Exemplo de valor: 1 (gateway local).
 6. **Ip:** Endereço IP (ou nome) do hop analisado. Pode ser _gateway, IPs reais, etc. Exemplo de valor: 100.68.0.1 ou _gateway.
 7. **Loss:** Porcentagem de pacotes perdidos (loss) para aquele hop.
 8. **Snt:** Quantidade de pacotes enviados (Sent) para aquele hop durante o teste.
 9. **Last:** Latência (em milissegundos) da última medição de ping naquele hop.
10. **Avg:** Latência média (em ms) considerando todas as medições naquele hop.
11. **Best:** Melhor (menor) tempo de resposta observado (em ms).
12. **Wrst:** Pior (maior) tempo de resposta observado (em ms).
13. **StDev:** Desvio padrão (em ms) da latência, calculado a partir das medições.

---

## Importando Dados no SQLite

Se quiser **verificar** os dados armazenados, use o próprio SQLite:

```bash
sqlite3 mtr_data.db

-- Exemplo de consulta:
SELECT * FROM mtr_data LIMIT 10;
```

Isso listará as 10 primeiras entradas. Você também pode usar ferramentas como [DB Browser for SQLite](https://sqlitebrowser.org/) para visualização mais amigável.


## Agendamento com Crontab

Para rodar a cada 5 minutos automaticamente:

1. Edite o **crontab**:
   ```bash
   crontab -e
   ```
2. Adicione uma linha (ajuste o caminho completo do script):
   ```bash
   */5 * * * * /home/usuario/mtr-log/monitor.sh
   ```
3. Salve o arquivo. O script será executado a cada 5 minutos, gerando um novo CSV e importando os dados.


## Customizações

* **Alterar o alvo**: No script `run_mtr.sh`, procure pela variável `ALVO="8.8.8.8"` e mude para o IP ou hostname que deseja monitorar.
* **Quantidade de pacotes (ciclos)**: Ajuste a opção `-c 5` para outro valor se quiser mais/menos amostragem.
* **Estrutura da Tabela**: Se quiser armazenar mais dados (IP do hop, ou timestamp etc.), edite a função `setup_database` no script e adapte a forma que o CSV é gerado (por exemplo, usando `-o "colunas"` no MTR).
* **Rodar em IPv6**: Acrescente `-6` no comando do MTR, se seu sistema tiver IPv6 configurado.


## Licença

Este projeto está licenciado sob a [MIT License](LICENSE) - sinta-se livre para usá-lo, modificá-lo e distribuí-lo conforme suas necessidades.


**Dúvidas ou sugestões?**
Crie uma [Issue](https://github.com/seu-usuario/mtr-monitor/issues) neste repositório ou envie um Pull Request!