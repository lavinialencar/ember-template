# Contribuir

Obrigado por querer ajudar. Algumas regras curtas:

1. **Nunca use dado real.** Nem seu, nem de ninguém. Use a demo (`python3 scripts/gerar_exemplo.py`) e dado inventado: nomes com "Exemplo" ou "Modelo", e-mail em `example.com`, UUID começando com `00000000-0000-`, CPF inválido.
2. **Só biblioteca padrão do Python.** Os scripts não têm dependência de terceiros, e isso é de propósito.
3. **Regra genérica no código, regra pessoal no JSON.** O que vale pra qualquer pessoa no Brasil vai em `scripts/`. O que depende de quem você é vai em `data/regras_privadas.json`, que nunca sobe.
4. **Antes de abrir o pull request:**

   ```sh
   python3 -m unittest discover -s tests
   python3 tools/checar_dados_pessoais.py
   ```

   Os dois precisam passar. O CI roda os mesmos, mais a demo ponta a ponta e o `gitleaks`.
5. **Mudou comportamento, mude o guia.** A documentação mora em `docs/`. Diagrama em `assets/`, em SVG escrito à mão.
6. **Português do Brasil**, frase curta, segunda pessoa.

Falha de segurança não vai em issue: veja [SECURITY.md](SECURITY.md).

O passo a passo completo está em [docs/10-desenvolver.md](docs/10-desenvolver.md).
