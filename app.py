
import logging
import sqlite3
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= CONFIGURACOES =================
TITULO = "Indicador de Compra de Euro"
API_URL = "https://api.frankfurter.dev/v2/rate/eur/brl"
BANCO = "historico_euro.db"

logging.basicConfig(
    filename="indicador.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(
    page_title=TITULO,
    page_icon="💶",
    layout="wide",
)


# ================= BANCO DE DADOS =================
def conectar():
    return sqlite3.connect(BANCO, timeout=15)


def iniciar_banco():
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cotacoes (
                data TEXT PRIMARY KEY,
                taxa REAL NOT NULL,
                consultado_em TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                alvo REAL NOT NULL,
                taxa REAL NOT NULL,
                enviado_em TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(data, alvo)
            )
        """)


def salvar_cotacao(data, taxa):
    agora = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    with conectar() as conn:
        conn.execute("""
            INSERT INTO cotacoes (data, taxa, consultado_em)
            VALUES (?, ?, ?)
            ON CONFLICT(data) DO UPDATE SET
                taxa = excluded.taxa,
                consultado_em = excluded.consultado_em
        """, (data, taxa, agora))


def carregar_historico():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT data, taxa, consultado_em "
            "FROM cotacoes ORDER BY data",
            conn,
        )


def carregar_alertas():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT data, alvo, taxa, enviado_em, status "
            "FROM alertas ORDER BY id DESC",
            conn,
        )


# ================= CONSULTA DA API =================
def consultar_cotacao():
    try:
        resposta = requests.get(API_URL, timeout=20)
        resposta.raise_for_status()
        dados = resposta.json()

        if dados.get("base") != "EUR":
            raise ValueError("A moeda base retornada não é EUR.")

        if dados.get("quote") != "BRL":
            raise ValueError("A moeda de destino não é BRL.")

        taxa = float(dados["rate"])
        data = str(dados["date"])

        if taxa <= 0:
            raise ValueError("A taxa retornada é inválida.")

        salvar_cotacao(data, taxa)

        logging.info(
            "Cotação consultada: data=%s, taxa=%.4f",
            data,
            taxa,
        )

        return {
            "taxa": taxa,
            "data": data,
            "erro": None,
        }

    except Exception as erro:
        logging.exception("Erro ao consultar a API")

        return {
            "taxa": None,
            "data": None,
            "erro": str(erro),
        }


# ================= NOTIFICACAO NTFY =================
def obter_topico_ntfy():
    try:
        return st.secrets.get("ntfy_topic", "").strip()
    except Exception:
        return ""


def enviar_notificacao(mensagem):
    topico = obter_topico_ntfy()

    if not topico:
        return False, "Configure ntfy_topic para ativar notificações."

    try:
        resposta = requests.post(
            f"https://ntfy.sh/{topico}",
            data=mensagem.encode("utf-8"),
            headers={
                "Title": "Alerta de compra de euro",
                "Priority": "high",
                "Tags": "bell",
            },
            timeout=15,
        )

        resposta.raise_for_status()
        return True, "Notificação enviada."

    except Exception as erro:
        logging.exception("Erro ao enviar notificação ntfy")
        return False, str(erro)


def verificar_alerta(data, taxa, alvo):
    if taxa > alvo:
        return

    with conectar() as conn:
        registro = conn.execute(
            "SELECT status FROM alertas WHERE data = ? AND alvo = ?",
            (data, float(alvo)),
        ).fetchone()

    # Não repete um alerta que já foi enviado com sucesso.
    if registro and registro[0] == "Enviado":
        return

    mensagem = (
        f"O euro chegou a R$ {taxa:.4f}. "
        f"Seu preço-alvo é R$ {alvo:.2f}. "
        f"Data da taxa de referência: {data}."
    )

    sucesso, detalhe = enviar_notificacao(mensagem)
    status = "Enviado" if sucesso else f"Pendente: {detalhe}"

    agora = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    with conectar() as conn:
        conn.execute("""
            INSERT INTO alertas
                (data, alvo, taxa, enviado_em, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(data, alvo) DO UPDATE SET
                taxa = excluded.taxa,
                enviado_em = excluded.enviado_em,
                status = excluded.status
        """, (data, float(alvo), taxa, agora, status))

    if sucesso:
        st.toast("Notificação de euro enviada!", icon="🔔")
    else:
        logging.warning("Alerta pendente: %s", detalhe)


# ================= PAINEL PRINCIPAL =================
st_autorefresh(
    interval=60 * 60 * 1000,
    key="atualizacao_horaria",
)

iniciar_banco()

st.title("💶 Indicador de Compra de Euro")

st.markdown(
    "Acompanhe a taxa EUR/BRL, defina seu preço-alvo "
    "e consulte o histórico de cotações."
)

with st.sidebar:
    st.header("⚙️ Configurações")

    alvo = st.number_input(
        "Preço-alvo (R$)",
        min_value=0.01,
        max_value=100.00,
        value=5.50,
        step=0.05,
        format="%.2f",
    )

    st.divider()

    st.write("**Atualização do painel:** 1 hora")
    st.write("**Fonte:** Frankfurter API")

    st.caption(
        "A taxa de referência pode não refletir o preço "
        "final cobrado pelo banco ou casa de câmbio."
    )

with st.spinner("Consultando cotação do euro..."):
    resultado = consultar_cotacao()

taxa_atual = resultado["taxa"]
data_taxa = resultado["data"]

if taxa_atual is None:
    st.error("Não foi possível consultar a cotação.")

    st.write("Detalhe:", resultado["erro"])

    historico = carregar_historico()

    if not historico.empty:
        ultima = historico.iloc[-1]

        st.info(
            f"Última cotação salva: R$ {ultima['taxa']:.4f} "
            f"(data: {ultima['data']})."
        )

else:
    verificar_alerta(data_taxa, taxa_atual, float(alvo))

    diferenca = taxa_atual - float(alvo)

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Cotação EUR/BRL",
        f"R$ {taxa_atual:.4f}",
    )

    col2.metric(
        "Preço-alvo",
        f"R$ {alvo:.2f}",
    )

    col3.metric(
        "Diferença para o alvo",
        f"R$ {diferenca:.4f}",
        delta=f"{diferenca:.4f}",
        delta_color="inverse",
    )

    if taxa_atual <= alvo:
        st.success(
            f"A cotação atingiu seu alvo! "
            f"R$ {taxa_atual:.4f} ≤ R$ {alvo:.2f}"
        )
    else:
        st.warning(
            f"O euro está R$ {taxa_atual - alvo:.4f} "
            "acima do seu preço-alvo por euro."
        )

    st.caption(
        f"Data da taxa de referência: {data_taxa}"
    )

st.divider()


# ================= HISTORICO E GRAFICO =================
st.subheader("📈 Histórico da cotação")

historico = carregar_historico()

if historico.empty:
    st.info(
        "O histórico ainda está vazio. "
        "Ele será preenchido após a primeira consulta bem-sucedida."
    )

else:
    historico["data"] = pd.to_datetime(
        historico["data"],
        errors="coerce",
    )

    historico = historico.dropna(subset=["data"])
    historico = historico.sort_values("data")

    grafico = historico.set_index("data")[["taxa"]]
    grafico = grafico.rename(
        columns={"taxa": "Cotação (R$/EUR)"}
    )

    st.line_chart(grafico)

    tabela = historico.sort_values(
        "data",
        ascending=False,
    ).copy()

    tabela["data"] = tabela["data"].dt.strftime("%d/%m/%Y")

    tabela = tabela.rename(columns={
        "data": "Data da taxa",
        "taxa": "Cotação (R$/EUR)",
        "consultado_em": "Última consulta",
    })

    st.dataframe(
        tabela,
        use_container_width=True,
        hide_index=True,
    )

    csv = historico.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        label="⬇️ Baixar histórico em CSV",
        data=csv,
        file_name="historico_euro.csv",
        mime="text/csv",
    )

st.divider()

# ================= HISTORICO DE ALERTAS =================
st.subheader("🔔 Histórico de alertas")

alertas = carregar_alertas()

if alertas.empty:
    st.info("Nenhum alerta registrado até o momento.")

else:
    alertas = alertas.rename(columns={
        "data": "Data da taxa",
        "alvo": "Preço-alvo (R$)",
        "taxa": "Cotação (R$/EUR)",
        "enviado_em": "Data do alerta",
        "status": "Status",
    })

    st.dataframe(
        alertas,
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ================= CONFIGURAR NOTIFICACOES =================
with st.expander("📱 Como receber alertas no celular"):
    st.markdown("""
1. Instale o aplicativo ntfy no celular.
2. Acesse https://ntfy.sh e escolha um tópico aleatório,
   difícil de adivinhar.
3. Assine esse mesmo tópico no aplicativo do celular.
4. Dentro da pasta do projeto, crie a pasta `.streamlit`,
   caso ainda não exista.
5. Dentro dela, crie o arquivo `secrets.toml`.
6. Coloque nele o conteúdo abaixo, substituindo o exemplo
   pelo seu tópico:

```toml
ntfy_topic = "seu-topico-aleatorio"
```

7. Salve e reinicie o Streamlit.

Use um tópico imprevisível: tópicos públicos podem ser
acessados por outras pessoas que conheçam seu nome.
""")

st.caption(
    "Indicador informativo. A taxa Frankfurter é uma taxa de "
    "referência diária, não uma cotação comercial em tempo real. "
    "Antes de comprar, confira IOF, spread e tarifas."
)
