# Backup

`scripts/backup.py` junta `data/` e `.env` num `.tar.gz` e cifra com a sua chave pública (`openssl cms`, AES-256). O resultado vai pra `BACKUP_DESTINO`, uma pasta que pode ser sincronizada com a nuvem.

A ideia é simples: a máquina que roda o Ember só tem o certificado público, que sabe trancar mas não sabe abrir. A chave privada, que abre, fica fora da máquina, no seu gerenciador de senhas. Quem achar o arquivo na nuvem, ou roubar a máquina, não lê o backup.

## O que você precisa

- OpenSSL 3. Confira com `openssl version`.
- No macOS, o `openssl` do sistema é LibreSSL e falha com chave de curva elíptica (`error setting recipientinfo`). Instale o do Homebrew (`brew install openssl@3`) e deixe ele primeiro no `PATH`, inclusive no agendamento (veja [02-instalar.md](02-instalar.md#macos-com-launchd)). Outra saída: aponte a variável `OPENSSL` pro binário certo (`OPENSSL=$(brew --prefix openssl@3)/bin/openssl`). O `backup.py` confere a versão antes de cifrar e para com uma mensagem clara se não for OpenSSL 3.
- O contêiner `ember-scripts` já vem com OpenSSL 3.

## 1. Gerar o par de chaves

Faça num computador de confiança, numa pasta temporária só sua:

```sh
mkdir -m 700 ~/ember-chave && cd ~/ember-chave
openssl ecparam -name secp384r1 -genkey -noout -out privada.pem
openssl req -new -x509 -key privada.pem -out backup_cert.pem -days 3650 -subj "/CN=Ember backup"
```

- `privada.pem` é a chave privada (curva P-384). Ela abre os backups.
- `backup_cert.pem` é o certificado autoassinado com a chave pública. Ele só tranca.

## 2. Guardar cada metade no lugar certo

1. Abra `privada.pem` e guarde o conteúdo inteiro no seu gerenciador de senhas, como nota segura ou anexo.
2. Copie o certificado pra máquina do Ember:

   ```sh
   cp ~/ember-chave/backup_cert.pem /caminho/do/ember-template/scripts/backup_cert.pem
   ```

   Esse é o caminho padrão. Se preferir outro lugar, aponte `BACKUP_CERT` no `.env`. O `.gitignore` já ignora `*.pem`, `*.key` e `*.cms`.

3. Apague a pasta temporária:

   ```sh
   rm -rf ~/ember-chave
   ```

A chave privada não deve ficar em disco na máquina do Ember, nem em `data/`, nem no repositório.

## 3. Ligar o backup

No `.env`:

```
BACKUP_DESTINO=/caminho/da/pasta/de/backup
```

Teste:

```sh
python3 scripts/backup.py
```

Deve aparecer `backup: ember-AAAA-MM-DD.tar.gz.cms (N KB), 1 guardados`. Sem `BACKUP_DESTINO` ou sem o certificado, o script para com uma mensagem clara. Pra rodar a rotina sem backup: `atualizar.py --sem-backup`.

## Retenção

- Um arquivo por dia: `ember-AAAA-MM-DD.tar.gz.cms`. Rodar duas vezes no mesmo dia sobrescreve o do dia.
- Ficam os 12 mais recentes. Os mais velhos são apagados a cada rodada.
- Com a rotina diária, isso dá uns 12 dias de histórico. Se quiser guardar mais, copie um arquivo por mês pra outro lugar.

## Restaurar

Teste a restauração uma vez logo depois de configurar. Backup que nunca foi aberto não é backup.

1. Copie a chave privada do gerenciador de senhas pra um arquivo temporário:

   ```sh
   mkdir -m 700 ~/ember-restaurar && cd ~/ember-restaurar
   # cole o conteúdo em privada.pem, com permissão 600
   ```

2. Decifre e extraia:

   ```sh
   openssl cms -decrypt -inform DER -in /caminho/ember-AAAA-MM-DD.tar.gz.cms -inkey privada.pem | tar xz
   ```

   Saem `data/` e `.env`, como estavam no dia do backup.

3. Copie `data/` e `.env` pro repositório (com o Ember parado) e confira as permissões:

   ```sh
   chmod 700 data && chmod 600 .env
   ```

4. Apague a chave temporária:

   ```sh
   rm ~/ember-restaurar/privada.pem
   ```

## Se perder a chave privada

Os backups antigos ficam ilegíveis pra sempre. Gere um par novo (passo 1), troque o certificado e faça um backup novo na hora.

## Se a chave privada vazar

Gere um par novo, troque o certificado e apague os backups antigos do destino: quem tem a chave antiga abre todos eles. Troque também os segredos do `.env`, porque ele vai dentro do backup.

Próximo: [09-seguranca.md](09-seguranca.md).
