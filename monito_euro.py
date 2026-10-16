import os
import requests

API_URL = "https://api.frankfurter.dev/v2/rate/eur/brl"

def main():
    topico = os.getenv("NTFY_TOPIC", "").strip()
    alvo = float(os.getenv("EURO_ALVO", "6.00"))

    if not topico:
        raise ValueError("Configure o segredo NTFY_TOPIC no GitHub.")

    resposta = requests.get(API_URL, timeout=20)
    resposta.raise_for_status()
    dados = resposta.json()

    taxa = float(dados["rate"])
    data = dados["date"]

    print(f"Data da taxa: {data}")
    print(f"Cotação: R$ {taxa:.4f}")
    print(f"Preço-alvo: R$ {alvo:.2f}")

    if taxa <= alvo:
        mensagem = (
            f"O euro atingiu R$ {taxa:.4f}. "
            f"Seu alvo é R$ {alvo:.2f}. "
            f"Data da taxa: {data}."
        )

        envio = requests.post(
            f"https://ntfy.sh/{topico}",
            data=mensagem.encode("utf-8"),
            headers={"Title": "Alerta de compra de euro"},
            timeout=20,
        )
        envio.raise_for_status()
        print("Notificação enviada!")
    else:
        print("Euro acima do alvo. Nenhum alerta enviado.")

if __name__ == "__main__":
    main()

