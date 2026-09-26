# Política de segurança

## Versão suportada

Só a branch `main` recebe correção. Não há versões numeradas.

## Como relatar uma falha

Relate em particular, pelo GitHub:

1. Abra a aba **Security** do repositório.
2. Clique em **Report a vulnerability**.
3. Descreva o problema, como reproduzir e o impacto que você vê.

Não abra issue pública, pull request ou discussão sobre a falha antes de uma correção sair.

Não mande dado financeiro real no relato. Se precisar de um exemplo, use a demo (`python3 scripts/gerar_exemplo.py`) ou dado inventado.

## O que esperar

- Uma primeira resposta assim que alguém puder ler. O projeto é mantido por voluntários, sem prazo garantido.
- Se a falha for confirmada, a correção sai na `main` e o aviso de segurança é publicado depois, com crédito a você, se quiser.

## Escopo

Dentro:

- os scripts em `scripts/` e `tools/`;
- o webhook dos botões (`scripts/agendador.py`) e a assinatura dos botões (`scripts/notificar.py`);
- o painel gerado (`scripts/painel_template.html`, `scripts/painel_montar.py`): CSP, SRI, escape;
- os arquivos de compose, o `Dockerfile.scripts`, as migrations em `sql/` e o fluxo em `n8n/`;
- o CI em `.github/`;
- a documentação, quando ela ensina a fazer algo inseguro.

Fora:

- falhas na Pluggy, no MeuPluggy, no ntfy, no Tailscale, no n8n, no Postgres, na BrasilAPI ou no TickTick (relate a quem mantém cada um);
- ataques que já partem de uma máquina comprometida ou do seu usuário do sistema (veja [docs/09-seguranca.md](docs/09-seguranca.md#o-que-não-está-protegido));
- instalação que contraria a documentação, como abrir porta em `0.0.0.0` ou publicar o painel.
