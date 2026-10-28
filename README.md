<div align="center">

# Ressoa

**o que a música te faz sentir**

Um diário musical para guardar lembranças, compartilhar sentimentos e descobrir pessoas através da música.

[Acessar o Ressoa](https://ressoa.onrender.com) · [Funcionalidades](#funcionalidades) · [Tecnologias](#tecnologias) · [Hospedagem](#hospedagem)

</div>

## Sobre o projeto

O Ressoa nasceu da ideia de que uma música pode dizer muito sobre um momento. Cada publicação, chamada de **Ressoa**, reúne uma faixa e aquilo que ela representa para quem está ouvindo: um comentário, uma lembrança ou um trecho da letra.

O site combina um diário pessoal com uma rede social. Você pode guardar suas músicas, acompanhar outras pessoas e escolher uma faixa para representar a semana. A interface usa tema escuro, capas de álbuns e uma identidade inspirada em discos, dando espaço para a música e para o texto de cada pessoa.

O projeto está disponível em **[ressoa.onrender.com](https://ressoa.onrender.com)**. Para publicar, interagir e acessar os perfis, é necessário criar uma conta.

## Funcionalidades

- **For you:** navegação entre Ressoas, prévias de áudio sobre as capas e prioridade para pessoas que você segue. Publicações comuns aparecem no feed por 24 horas e continuam disponíveis no perfil.
- **Meus sons:** diário em blocos, com criação, edição, exclusão e controle de visibilidade das publicações.
- **Ressoa da semana:** uma escolha por semana, independente do diário e em destaque no feed e no perfil.
- **Músicas e letras:** busca de faixas, capas, metadados, prévias e seleção de um trecho da letra para compor a publicação, conforme disponibilidade.
- **Perfil:** foto, bio, até seis músicas favoritas, publicações fixadas, reposts e capa de fundo personalizável.
- **Conexões:** busca de pessoas, seguidores, contas privadas e aprovação de solicitações para seguir.
- **Interações:** curtidas sem contagem pública, reposts e Ressoas salvos. O autor pode consultar quem curtiu ou repostou.
- **Compartilhamento:** prévia da imagem, download do Ressoa e cópia do link. Após entrar ou criar uma conta pelo link, a pessoa chega à publicação compartilhada.
- **Contas:** cadastro, login por e-mail ou usuário e opção de manter a sessão no dispositivo.

## Tecnologias

| Parte | Implementação |
| --- | --- |
| Interface | HTML, CSS responsivo e JavaScript com módulos ES |
| Backend | Python e API HTTP sobre WSGI |
| Banco local | SQLite |
| Banco de produção | PostgreSQL no Neon, com Psycopg |
| Servidor | Gunicorn em contêiner Docker, hospedado no Render |
| Música | Catálogo e prévias Deezer, embeds Spotify e letras via LRCLIB |

### Como funciona

O navegador carrega a interface e conversa com a API Python na mesma origem. O backend cuida do cadastro, das sessões, das regras de publicação e das permissões de acesso aos perfis. As consultas aos serviços de música também passam pelo servidor.

Contas, publicações, favoritas, seguidores e interações ficam no banco. O desenvolvimento usa SQLite; a versão hospedada usa PostgreSQL no Neon. As regras do aplicativo são compartilhadas entre os dois bancos.

As senhas são armazenadas com PBKDF2-SHA256. As sessões usam cookies HttpOnly e SameSite, com Secure em produção. Privacidade, autoria das publicações e o limite semanal são verificados pelo backend. Edições e interações são gravadas em transações; o controle de versão evita que uma aba antiga sobrescreva uma alteração mais recente.

### Estrutura

```text
ressoa/
├── web/                    # Interface, módulos JavaScript, estilos e assets
├── webapp.py               # Aplicação WSGI e rotas HTTP
├── database.py             # Persistência e regras de negócio
├── postgres_storage.py     # Adaptação das consultas para PostgreSQL
├── services.py             # Integrações musicais
├── serve.py                # Servidor de desenvolvimento
├── Dockerfile              # Imagem da aplicação
├── gunicorn.conf.py        # Configuração do servidor de produção
└── render.yaml             # Configuração de hospedagem
```

## Hospedagem

A versão online roda no **Render**, com os dados no **Neon**. O Dockerfile define a imagem e o comando do Gunicorn; `render.yaml` contém a configuração do serviço.

| Variável | Valor em produção |
| --- | --- |
| `RESSOA_ENV` | `production` |
| `DATABASE_URL` | Conexão PostgreSQL do Neon, cadastrada como segredo no Render |
| `APP_ORIGIN` | URL HTTPS de um domínio próprio, quando utilizado |

No endereço padrão do Render, a origem é obtida de `RENDER_EXTERNAL_HOSTNAME`. O servidor escuta em `0.0.0.0:$PORT`.

`/healthz` confirma que o servidor está respondendo, sem abrir conexão com o banco. É o endereço usado pelo Render e indicado para um monitor externo a cada cinco minutos. `/readyz` verifica também o acesso ao PostgreSQL e serve para diagnóstico; consulte-o quando necessário, para permitir que o Neon suspenda o processamento durante períodos sem uso.

Contas e publicações permanecem no Neon ao atualizar a aplicação. Uma instalação nova cria apenas as tabelas, sem usuários ou Ressoas de exemplo. O banco local e as credenciais ficam fora do Git. A retenção dos backups de produção é configurada no próprio Neon.

Como a hospedagem atual usa o plano gratuito do Render, a abertura pode demorar após um período sem acessos. Um monitor externo pode reduzir essa espera, sujeito aos limites do plano. O monitor precisa estar configurado e ativo fora da aplicação; este repositório não instala agendamentos por conta própria.

Recuperação de senha por e-mail e ferramentas de moderação ainda não estão implementadas.
