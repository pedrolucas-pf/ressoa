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

- **For you:** até 10 Ressoas por seleção, com prévias de áudio sobre as capas. Os ainda não vistos aparecem primeiro, do mais recente ao mais antigo; em datas iguais, quem você segue tem prioridade. Os já vistos continuam disponíveis e circulam começando pelos vistos há mais tempo. A aba **Seguindo** mostra apenas publicações dos perfis seguidos, com a mesma ordenação. Ao avançar depois do último, outra seleção ocupa o lugar da anterior; sem outras publicações elegíveis, a sequência volta ao início. Publicações comuns aparecem no feed por 24 horas e continuam disponíveis no perfil.
- **Meus sons:** diário em blocos, com criação, edição, exclusão e controle de visibilidade das publicações.
- **Feed em todos os dispositivos:** rolagem vertical com inércia e encaixe em For you e Seguindo, usando toque, mouse ou trackpad. No primeiro, puxar para baixo atualiza; no último, outro gesto para cima renova a seleção. As setas do teclado também permitem navegar.
- **Ressoa da semana:** uma escolha por semana, independente do diário e em destaque no feed e no perfil.
- **Músicas e letras:** busca de faixas com páginas de resultados, pesquisa alternativa sem acentos e importação por link do Deezer ou Spotify. O catálogo Deezer funciona sem conexão externa; com Spotify conectado, também é possível buscar no catálogo oficial e alternar entre os dois. Quando a LRCLIB fornece os tempos dos versos, o seletor destaca e sugere a letra do áudio escolhido. Selecionar outros versos pode ajustar a janela de áudio ao primeiro verso, com opção de desativar a sincronização ou escrever livremente. Letras sem horários e prévias Deezer mantêm a seleção manual. Capas, metadados, prévias e letras dependem da disponibilidade da faixa.
- **Trecho de áudio:** uma janela de 30 segundos que pode ser arrastada pela faixa, tanto no diário quanto no Ressoa da semana. Com Spotify Premium conectado, é possível escolher qualquer ponto da música; cada ouvinte precisa conectar sua própria conta Premium para ouvir esse trecho. A seleção também funciona pelo teclado. Sem conexão Spotify, a opção **Prévias** usa o Deezer sem exigir login externo. Trechos mais curtos salvos anteriormente são preservados. A escolha é salva com a publicação e acompanha o play no feed, perfil e leitura.
- **Perfil:** foto, bio, até seis músicas favoritas, publicações fixadas, reposts e capa de fundo personalizável.
- **Conexões:** busca de pessoas, seguidores, contas privadas e aprovação de solicitações para seguir.
- **Notificações:** o ícone de pessoa com “+” reúne seguidores, solicitações, curtidas e reposts, com contador vermelho, data e hora. Avisos de interação abrem o Ressoa correspondente. É possível confirmar ou excluir pedidos, seguir de volta e remover avisos pelo “×”. Avisos expiram após sete dias; pedidos pendentes permanecem até serem confirmados ou excluídos. A leitura é salva na conta. O contador atualiza a cada 30 segundos enquanto o site está aberto; solicitações enviadas são conferidas a cada cinco segundos para refletir aprovações sem recarregar a página.
- **Comentários:** conversas nos Ressoas, com o ícone à direita da curtida, carregamento em páginas e texto de até 1.000 caracteres. Cada novo comentário de outra pessoa avisa o dono da publicação; o aviso mostra apenas quem comentou, sem o texto, e abre a conversa ao clicar. Quem escreveu e o dono da publicação podem apagar um comentário. As permissões da publicação e do perfil são conferidas no servidor em cada leitura, envio e exclusão.
- **Apresentação:** abaixo do login, capas de discos brasileiros, um vinil e notas do diário apresentam o Ressoa, com explicações curtas sobre perfil, trechos, visibilidade e conexões.
- **Interações:** curtidas sem contagem pública, reposts e Ressoas salvos. O autor pode consultar quem curtiu ou repostou.
- **Compartilhamento:** prévia da imagem com a marca Ressoa no rodapé, download do Ressoa e cópia do link. Após entrar ou criar uma conta pelo link, a pessoa chega à publicação compartilhada.
- **Contas:** cadastro, login por e-mail ou usuário e opção de manter a sessão no dispositivo.

Nomes de usuário diferenciam maiúsculas e minúsculas: `DAss` e `dass` podem pertencer a contas distintas. O login por usuário exige a escrita exata do cadastro; por e-mail, essa diferença não é exigida.

## Tecnologias

| Parte | Implementação |
| --- | --- |
| Interface | HTML, CSS responsivo e JavaScript com módulos ES |
| Backend | Python e API HTTP sobre WSGI |
| Banco local | SQLite |
| Banco de produção | PostgreSQL no Neon, com Psycopg |
| Servidor | Gunicorn em contêiner Docker, hospedado no Render |
| Música | Deezer, Spotify Web API e Web Playback SDK opcionais, embeds públicos e letras via LRCLIB |

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
├── spotify.py              # Autorização PKCE, renovação de acesso e API Spotify
├── mail.py                 # Recuperação de senha pela API de e-mail
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
| `BREVO_API_KEY` | Chave privada da API da Brevo, para recuperar senhas |
| `EMAIL_FROM` | Endereço remetente verificado na Brevo |
| `EMAIL_FROM_NAME` | Nome do remetente; padrão: `Ressoa` |
| `GOOGLE_SITE_VERIFICATION` | Valor `content` da tag HTML do Google Search Console, quando configurado |
| `SPOTIFY_CLIENT_ID` | Client ID público do aplicativo Spotify; opcional, habilita conexão, busca e seleção na faixa completa |

No endereço padrão do Render, a origem é obtida de `RENDER_EXTERNAL_HOSTNAME`. O servidor escuta em `0.0.0.0:$PORT`.

`/healthz` confirma que o servidor está respondendo, sem abrir conexão com o banco. É o endereço usado pelo Render e indicado para um monitor externo a cada cinco minutos. `/readyz` verifica também o acesso ao PostgreSQL e serve para diagnóstico; consulte-o quando necessário, para permitir que o Neon suspenda o processamento durante períodos sem uso.

Contas e publicações permanecem no Neon ao atualizar a aplicação. Uma instalação nova cria apenas as tabelas, sem usuários ou Ressoas de exemplo. O banco local e as credenciais ficam fora do Git. A retenção dos backups de produção é configurada no próprio Neon.

### Conexão com Spotify

1. No [Dashboard do Spotify](https://developer.spotify.com/dashboard), crie um aplicativo com **Web API** e **Web Playback SDK**. Cadastre o site `https://ressoa.onrender.com` e o endereço de retorno **exato** `https://ressoa.onrender.com/api/spotify/callback`.
2. No Render, configure `SPOTIFY_CLIENT_ID` com o Client ID público e publique a aplicação. O fluxo usa [Authorization Code com PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), sem Client Secret.
3. No Ressoa, use o ícone Spotify ao lado da busca no cabeçalho ou **Conectar Spotify** na busca de músicas e na edição do perfil. A autorização abre uma janela separada para manter o editor aberto. Com a conta conectada, o ícone abre as opções da conexão. Selecione Spotify na busca, escolha a faixa e abra **Escolher trecho de áudio**. Arraste a janela de 30 segundos até a parte desejada e use **Ouvir trecho** para conferir. O áudio aparece antes da seleção da letra. A opção **Prévias** continua disponível pelo Deezer, sem conectar uma conta.

A sincronização de versos usa os horários LRC disponíveis na [API da LRCLIB](https://lrclib.net/docs.txt). A letra sugerida respeita o limite de três versos e 120 caracteres; pode ser trocada ou digitada. Refrões repetidos mantêm seus horários separados. Se os versos escolhidos estiverem distantes demais para uma janela de 30 segundos, o áudio é preservado e o seletor informa isso. A posição da prévia Deezer dentro da música completa não é conhecida, por isso ela não recebe um alinhamento estimado.

A autorização é vinculada à conta e à sessão que iniciaram a conexão, expira em dez minutos e é usada uma única vez. As autorizações de acesso e renovação ficam no banco do servidor; o token de renovação não vai ao navegador. O SDK recebe apenas o token de acesso da própria conta autenticada, em memória. **Desconectar Spotify** remove a conexão armazenada; não remove a conta Ressoa nem suas publicações. Os registros HTTP não incluem os parâmetros dos endereços.

O áudio é transmitido pelo Spotify, sem baixar ou guardar arquivos da gravação no Ressoa. A reprodução da faixa completa requer Premium, conforme a [documentação do SDK](https://developer.spotify.com/documentation/web-playback-sdk). Aplicativos novos ficam em modo de desenvolvimento, com usuários autorizados limitados; liberar para mais pessoas depende das [regras de acesso do Spotify](https://developer.spotify.com/documentation/web-api/concepts/quota-modes). Se o domínio mudar, atualize o endereço de retorno também no Dashboard.

Sem `SPOTIFY_CLIENT_ID`, a conexão permanece oculta e a busca Deezer, as prévias e o restante do site continuam disponíveis.

Como a hospedagem atual usa o plano gratuito do Render, a abertura pode demorar após um período sem acessos. Um monitor externo pode reduzir essa espera, sujeito aos limites do plano. O monitor precisa estar configurado e ativo fora da aplicação; este repositório não instala agendamentos por conta própria.

### Presença no Google

A página inicial tem título e descrição do produto, URL canônica e dados `WebSite` com o nome Ressoa. `/robots.txt` orienta o rastreamento e aponta para `/sitemap.xml`, que inclui apenas a página inicial pública. Perfis e publicações continuam protegidos pela autenticação. Os endereços acompanham `APP_ORIGIN` ou o domínio padrão informado pelo Render.

Para solicitar a indexação:

1. Abra o [Google Search Console](https://search.google.com/search-console/) com sua conta Google e adicione uma propriedade do tipo **Prefixo do URL**: `https://ressoa.onrender.com/`. Use esse tipo porque o domínio `onrender.com` pertence ao Render.
2. Escolha o método **Tag HTML**. Copie o valor `content` da tag `google-site-verification`. A configuração também aceita a tag HTML completa e extrai o código automaticamente.
3. No Render, em **Environment**, defina `GOOGLE_SITE_VERIFICATION` com esse valor. Salve, aguarde a atualização e clique em **Verificar** no Search Console. Mantenha a variável depois da confirmação.
4. Em **Sitemaps**, envie `sitemap.xml`.
5. Em **Inspeção de URL**, inspecione `https://ressoa.onrender.com/` e clique em **Solicitar indexação**. Acompanhe os relatórios de indexação e desempenho pelo Search Console.

Essas configurações ajudam o Google a descobrir e identificar o site; a indexação e a posição nos resultados dependem do Google e não são imediatas nem garantidas. Um domínio próprio pode facilitar a divulgação da marca, mas não é requisito para indexar o endereço atual. Consulte as orientações oficiais sobre [verificação](https://support.google.com/webmasters/answer/9008080?hl=pt-BR) e [solicitação de rastreamento](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl).

### Recuperação de senha

Na tela de entrada, **Esqueceu a senha?** envia um link ao e-mail cadastrado. Ele expira em 30 minutos e só pode ser usado uma vez. O banco armazena somente o hash do token; trocar a senha encerra as sessões anteriores sem alterar o perfil, as publicações ou as interações. A resposta do formulário não revela se um e-mail possui conta.

Para ativar o envio:

1. Crie uma conta na [Brevo](https://www.brevo.com/) e conclua a ativação dos e-mails transacionais.
2. Em **Senders / Remetentes**, cadastre e verifique um endereço de e-mail seu. Um domínio próprio autenticado é recomendado para melhorar a entrega.
3. Gere uma **chave de API** da Brevo (não a senha SMTP).
4. No Render, em **Environment**, cadastre `BREVO_API_KEY`, `EMAIL_FROM` e, se quiser, `EMAIL_FROM_NAME`. Salve e aguarde a atualização do serviço. Não coloque esses valores no GitHub.
5. Solicite a recuperação para uma conta de teste sua e confirme a entrega, a redefinição e o login com a nova senha. Consulte os registros transacionais da Brevo se houver falha na entrega.

A integração usa HTTPS, compatível com o plano gratuito do Render. Sem a chave e o remetente, o formulário informa que a recuperação ainda está indisponível. O link usa a origem pública configurada no servidor, e seu token fica no fragmento da URL, fora dos logs HTTP. Pedidos têm limites de frequência e uma fila pequena de envio; falhas do provedor são registradas sem expor endereços ou tokens.

Ferramentas de moderação ainda não estão implementadas.
