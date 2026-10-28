import { spotifyCatalog } from './spotify-catalog.js';

// Historical context is sourced; the listening notes are explicitly editorial.
export const musicDetails = [
  {
    credits: 'Milton Nascimento e Lô Borges; letra da versão posterior: Márcio Borges',
    history: 'A gravação de 1972 pertence ao álbum Clube da Esquina e apresenta a melodia sem versos. Em entrevista à EBC, Lô Borges relembra a formação do grupo em Belo Horizonte; o programa distingue a composição instrumental de Milton e Lô da versão com letra de Márcio Borges.',
    meaning: 'Nesta gravação, a expressão vem da melodia e da voz, sem uma narrativa verbal. A sensação de lembrança ou pertencimento é uma leitura possível da escuta, não uma história pessoal confirmada pelos compositores.',
    sources: [{ label: 'EBC — entrevista com Lô Borges', url: 'https://radios.ebc.com.br/na-trilha-da-historia/2019/03/na-trilha-da-historia-mostra-origens-do-clube-da-esquina' }]
  },
  {
    credits: 'Djavan',
    history: 'Oceano integra o disco Djavan, de 1989, que acabou conhecido pelo nome da faixa. A discografia oficial registra a participação do violonista Paco de Lucía no solo da gravação, parte da presença de sonoridades espanholas no álbum.',
    meaning: 'A canção aproxima a imensidão do amor da ausência de quem se ama. As imagens de água e de deserto podem ser lidas como maneiras de expressar entrega, solidão e desejo de reencontro.',
    sources: [{ label: 'Djavan — discografia oficial', url: 'https://djavan.com.br/discografia/djavan-oceano/' }]
  },
  {
    credits: 'Caetano Veloso',
    history: 'Lançada em Cinema Transcendental, de 1979, a faixa é uma composição de Caetano Veloso. O catálogo da Universal no canal oficial do artista identifica Caetano como compositor, letrista e produtor. A versão disponível aqui é a edição identificada como Remixed Original Album.',
    meaning: 'O tempo é tratado como um interlocutor ao qual se dirige uma oração. Uma leitura possível é a tentativa de conviver com a passagem da vida, reconhecendo tanto a transformação quanto o que permanece.',
    sources: [{ label: 'Caetano Veloso / Universal — ficha da gravação', url: 'https://www.youtube.com/watch?v=qNlPLFsBNbc' }]
  },
  {
    credits: 'Mallu Magalhães',
    history: 'Velha e Louca é uma faixa de Pitanga, álbum de Mallu Magalhães lançado em 2011. A canção também foi lançada como single naquele ano. A gravação associada aqui corresponde ao catálogo de Pitanga, não a uma versão ao vivo.',
    meaning: 'A voz da canção recusa o julgamento alheio e encontra alegria nas próprias imperfeições. Pode ser ouvida como uma afirmação de autonomia, humor e liberdade para seguir o próprio caminho.',
    sources: [{ label: 'Spotify — gravação de Pitanga', url: 'https://open.spotify.com/track/0UtoASDXmEeZklHfKlqz8s' }, { label: 'Spotify — single de 2011', url: 'https://open.spotify.com/album/4MMEmWKUwW2fjsz9s6ntv9' }]
  },
  {
    credits: 'Belchior',
    history: 'A faixa está em Alucinação, lançado em 1976. Segundo a Universal, o álbum tem produção de Mazzola e arranjos de José Roberto Bertrami. O disco aproxima experiências pessoais e os conflitos de uma geração em busca de mudança.',
    meaning: 'O narrador encontra força para continuar apesar do sofrimento vivido. O contraste entre a fragilidade e a insistência em sobreviver permite uma leitura de resistência e renovação, sem apagar as dificuldades.',
    sources: [{ label: 'Universal Music — história de Alucinação', url: 'https://www.universalmusic.com.br/2017/06/02/universal-music-e-polysom-relancam-no-formato-lp-o-album-alucinacao-de-belchior/' }]
  },
  {
    credits: 'Marisa Monte e Arnaldo Antunes',
    history: 'Ainda Bem faz parte de O Que Você Quer Saber de Verdade, de 2011. O site oficial de Marisa Monte credita a composição a Marisa e Arnaldo Antunes. O videoclipe tem participação de Anderson Silva e direção de Dora Jobim.',
    meaning: 'O encontro amoroso aparece como uma reabertura depois de um período de solidão. A letra pode ser lida como gratidão por recuperar a confiança no afeto e na possibilidade de compartilhar a vida.',
    sources: [{ label: 'Marisa Monte — composição e álbum', url: 'https://www.marisamonte.com.br/musicas_/ainda-bem/' }, { label: 'Marisa Monte — ficha do videoclipe', url: 'https://www.marisamonte.com.br/home/home/es/videos_/o-que-voce-quer-saber-de-verdade/' }]
  }
].map((detail, index) => ({ ...detail, ...spotifyCatalog.tracks[index] }));
