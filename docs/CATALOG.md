# Música, letras e compartilhamento

O Ressoa usa serviços diferentes para busca, reprodução e letras. Cada faixa mantém a identificação da sua origem, e a disponibilidade de conteúdo depende do provedor.

## Integrações

| Serviço | Uso no Ressoa |
| --- | --- |
| Deezer | Busca de músicas, capas, metadados e prévias de áudio |
| Spotify | Faixas adicionadas por link e reprodução pelo player oficial |
| LRCLIB | Consulta de letras por música e artista |

As rotas de busca, ficha e letras exigem uma sessão autenticada. O backend em `services.py` consulta os provedores; o navegador recebe os dados necessários para exibir a faixa.

### Busca e metadados

A busca textual consulta o catálogo público Deezer. Também é possível informar um link de faixa Spotify. Nesse caso, o servidor valida o domínio e o identificador antes de consultar o oEmbed e a página pública do player.

As músicas salvas em publicações, favoritas e fundos de perfil ficam no banco. `web/catalog-store.js` organiza os registros para a interface, e `web/track-context.js` compartilha consultas entre o player, a ficha e os seletores.

Metadados Deezer incluem álbum, duração, data de lançamento, participantes e outros campos disponíveis na resposta. A ficha distingue a data do álbum da data da edição da faixa. Os participantes são apresentados conforme os dados do catálogo.

A curadoria de contexto das seis faixas iniciais está em `web/music.js`. As APIs de música não fornecem uma interpretação editorial para todas as faixas; músicas adicionadas pela busca exibem os metadados disponíveis.

### Reprodução

O botão sobre a capa controla a prévia no feed, no diário, nos perfis e no leitor. Apenas uma reprodução fica ativa por vez. Trocar de publicação ou de aba, fechar o leitor ou iniciar outra música encerra a reprodução anterior.

- **Deezer:** usa o elemento `audio` com a URL de prévia devolvida pelo catálogo. O servidor atualiza os metadados da faixa para renovar URLs que possam expirar.
- **Spotify:** usa o embed e a iFrame API oficial. O controlador é criado quando necessário e removido ao encerrar a escuta. A disponibilidade do trecho é determinada pelo Spotify.

As prévias Deezer começam com volume `0.5`. Esse valor define o ganho inicial do player; o volume final também depende da gravação e do dispositivo. O volume do embed Spotify segue os controles oferecidos pelo próprio player.

## Letras

As letras são consultadas no LRCLIB, por título e artista, incluindo álbum e duração quando disponíveis. A interface mostra a fonte e distingue uma letra ausente de uma falha na consulta. As respostas são mantidas temporariamente em memória.

Ao escrever um Ressoa, a pessoa pode escolher **até três versos e 120 caracteres** para aparecerem sobre a capa esmaecida. O campo permite ajustar ou informar o trecho manualmente. A troca de música limpa a seleção anterior.

O trecho escolhido é salvo em `posts.lyric_excerpt`; a seleção do destaque semanal é independente da publicação no diário. A arte é renderizada por `web/post-art.js`.

## Imagens e links

O compartilhamento oferece uma prévia com duas ações: **Baixar ressoa** e **Copiar link**.

`web/share.js` desenha o cartão em canvas e exporta um PNG de **1080 × 1350 px**. A capa fica centralizada e o comentário aparece abaixo; textos longos são truncados para manter o tamanho da imagem. Quando há um trecho da letra selecionado, a imagem preserva essa composição.

O navegador tenta carregar a capa com CORS. Se ela não estiver disponível, o cartão pode ser gerado sem a imagem. O arquivo inclui a origem do catálogo e não contém áudio.

Os links seguem o formato `/#ressoa/ID`. A pessoa entra ou cria uma conta e retorna à publicação escolhida. O backend aplica as mesmas regras de privacidade dos perfis: um link não libera acesso a conteúdo privado.

Compartilhamentos não são registrados como interação. A lista do autor mostra apenas curtidas e reposts.

## Capas da tela de entrada

`web/assets/login-artwork.json` reúne 117 capas distintas de artistas de MPB e rock brasileiro. `web/login-artwork.js` carrega essa seleção e `web/auth.js` sorteia vinte capas sem repetição.

A rota pública `GET /api/login-artwork` fornece a seleção, com cache e limite de requisições. O arquivo local funciona como alternativa caso a consulta falhe. As imagens são carregadas do CDN Deezer.

## Configuração e manutenção

Os fluxos atuais não exigem chaves de API. O servidor precisa de acesso a `api.deezer.com`, `open.spotify.com` e `lrclib.net`. O navegador também acessa os CDNs de capas, as prévias e o player Spotify.

Para atualizar o catálogo Spotify inicial:

```sh
python scripts/sync_catalog.py
```

O script atualiza `web/spotify-catalog.js`. As músicas escolhidas pelas pessoas continuam armazenadas no banco.

Os testes de interface simulam as respostas musicais para verificar o comportamento do aplicativo. `scripts/verify_media.py` verifica separadamente a integração com os serviços reais, usando uma conta e um banco temporários.

## Referências

- [API Deezer](https://developers.deezer.com/api)
- [Spotify Embeds](https://developer.spotify.com/documentation/embeds)
- [Spotify oEmbed](https://developer.spotify.com/documentation/embeds/reference/oembed)
- [Spotify iFrame API](https://developer.spotify.com/documentation/embeds/references/iframe-api)
- [LRCLIB](https://lrclib.net/docs)
