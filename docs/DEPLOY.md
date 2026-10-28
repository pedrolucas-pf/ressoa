# Hospedagem e manutenção

O Ressoa está publicado em **https://ressoa.onrender.com**. A aplicação roda no Render e armazena as informações em PostgreSQL no Neon.

## Arquitetura

| Serviço | Responsabilidade |
| --- | --- |
| GitHub | Código-fonte, branch `main` |
| Render | Build Docker e execução do Gunicorn |
| Neon | Contas, sessões, publicações, perfis e interações |

O contêiner contém o backend Python e os arquivos de `web/`. O Gunicorn escuta em `0.0.0.0:$PORT`. A rota `/healthz` executa uma consulta ao banco e responde `{"ok": true}` quando a conexão está funcionando.

## Variáveis de ambiente

| Variável | Uso |
| --- | --- |
| `RESSOA_ENV` | `production` no serviço hospedado |
| `DATABASE_URL` | Conexão PostgreSQL do Neon, armazenada como segredo no Render |
| `APP_ORIGIN` | URL HTTPS do domínio próprio, sem barra final; opcional no endereço padrão do Render |
| `PORT` | Porta definida pela hospedagem |

Sem `APP_ORIGIN`, o backend usa `RENDER_EXTERNAL_HOSTNAME` para reconhecer a origem da interface. Em produção, `DATABASE_URL` é obrigatória; `DATABASE_PATH` não substitui o PostgreSQL.

O arquivo [`.env.example`](../.env.example) serve como referência. A aplicação lê as variáveis do ambiente, sem carregar um arquivo `.env` automaticamente.

## Configurar uma nova instalação

### Banco no Neon

1. Crie um projeto e um banco PostgreSQL na [console do Neon](https://console.neon.tech).
2. Escolha uma região próxima à hospedagem da aplicação, quando possível.
3. Em **Connect**, copie a conexão PostgreSQL com TLS. O projeto aceita a conexão com pooling.
4. Cadastre essa conexão como `DATABASE_URL` no painel do Render.

O backend cria as tabelas na inicialização. Uma instalação nova começa sem contas ou publicações de exemplo. Os dados do SQLite de desenvolvimento ficam apenas no ambiente local.

### Serviço no Render

Em **New → Web Service**, selecione o repositório GitHub e use:

| Campo | Valor |
| --- | --- |
| Branch | `main` |
| Runtime | Docker |
| Root Directory | Vazio |
| Dockerfile Path | `./Dockerfile` |
| Docker Command | Vazio, usando o comando do Dockerfile |
| Health Check Path | `/healthz` |

Configure as variáveis de ambiente e escolha o plano antes de iniciar o deploy. O [`render.yaml`](../render.yaml) também permite criar o serviço como Blueprint.

O plano Free é usado na hospedagem atual e suspende o serviço por inatividade. Para disponibilidade contínua, é necessário escolher um plano adequado no Render.

## Atualizar a aplicação

As alterações são enviadas para `main` no GitHub. Com o deploy automático habilitado no Render, o serviço é reconstruído a partir desse commit.

Os dados permanecem no Neon ao reiniciar ou atualizar o contêiner. A inicialização preserva as contas e publicações existentes.

Após uma atualização:

- Confira o resultado do build e do deploy no Render.
- Acesse a página inicial e `/healthz`.
- Confira os fluxos afetados pela alteração, como login, publicação e reprodução.

## Domínio próprio

O endereço atual é `ressoa.onrender.com`. Para conectar outro domínio:

1. Adicione o domínio em **Settings → Custom Domains** no Render.
2. Configure os registros DNS no provedor do domínio, seguindo os valores indicados pelo Render.
3. Verifique o domínio e aguarde a emissão do certificado HTTPS.
4. Defina `APP_ORIGIN` com a URL HTTPS escolhida e atualize o serviço.

## Backups

A retenção e a recuperação do banco de produção são configuradas no Neon, conforme os recursos do plano contratado.

Para criar uma cópia consistente do SQLite local:

```sh
python scripts/backup.py
```

As cópias ficam em `storage/backups/`. O script usa a API de backup do SQLite, incluindo as escritas que ainda estão no WAL. Ele não faz backup do PostgreSQL remoto.

`scripts/migrate_to_neon.py` é uma ferramenta de manutenção para uma migração planejada de SQLite. Não faz parte da inicialização nem da atualização normal do site.

## Referências

- [Web Services no Render](https://render.com/docs/web-services)
- [Limites do Render Free](https://render.com/docs/free)
- [Domínios próprios no Render](https://render.com/docs/custom-domains)
- [Conexão PostgreSQL no Neon](https://neon.com/docs/get-started/connect-neon)
