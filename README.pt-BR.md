# SerrebiTorrent

[English](README.md) | **Português (Brasil)**

Um gerenciador de torrents para Windows, desenvolvido com foco em uso por teclado e compatibilidade com leitores de tela. Permite gerenciar torrents localmente com o libtorrent integrado ou controlar um cliente remoto — qBittorrent, Transmission ou rTorrent — pela mesma interface.

[![Entre no SerrebiProjects no Telegram](https://img.shields.io/badge/Telegram-SerrebiProjects-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/SerrebiProjects)

**Dúvidas, bugs ou novidades sobre versões?** Entre no [grupo SerrebiProjects no Telegram](https://t.me/SerrebiProjects), o canal mais rápido para obter ajuda.

## Recursos

- Conecta ao libtorrent local ou a um cliente remoto qBittorrent, Transmission ou rTorrent (SCGI/XML-RPC), tudo pela mesma interface.
- Exibe velocidades de download/upload em tempo real, progresso, proporção, host do tracker e mensagens de status de cada torrent.
- Pesquisa indexadores de torrent e adiciona os itens escolhidos sem sair do aplicativo.
- Cria torrents.
- Interface responsiva: operações remotas são executadas em segundo plano para evitar travamentos da interface.
- Filtros rápidos (Todos, Baixando, Concluídos, Ativos) e árvore de trackers na barra lateral.
- Fluxo completo por teclado e suporte à bandeja do sistema, desenvolvido e testado com NVDA.
- Atualizador integrado que verifica SHA-256 e Authenticode antes de aplicar uma atualização, com backup e reversão automáticos.

## Download e instalação

Baixe a versão mais recente na [página de Releases](https://github.com/serrebidev/SerrebiTorrent/releases).

**Windows portátil**

1. Baixe o ZIP mais recente.
2. Extraia a pasta `SerrebiTorrent` inteira em algum local (exemplo: `C:\Portable\SerrebiTorrent\`).
3. Execute `SerrebiTorrent.exe` — não mova o EXE para fora da pasta.

O ZIP contém o runtime privado de Python do SerrebiTorrent, libtorrent, OpenSSL, interface web e o auxiliar de atualização. Um computador comum com Windows 11 64 bits não precisa ter Python, pip, ferramentas de compilação do Visual C++ nem outro cliente de torrent instalado.

Os dados portáteis (perfis, preferências, dados de retomada e logs) ficam ao lado do aplicativo em `SerrebiTorrent_Data\`. Atualizações feitas no mesmo local preservam esses dados.

**Linux x86-64**

1. Baixe o pacote Linux `.tar.gz`.
2. Extraia-o e execute `SerrebiTorrent/SerrebiTorrent`.

O pacote Linux inclui seu próprio runtime de Python e o libtorrent. Não é necessário instalar Python no sistema.

**macOS**

Baixe e extraia o ZIP de macOS gerado para a versão. Os pacotes de macOS são compilados em um runner nativo de macOS hospedado pelo GitHub e incluem o runtime de Python e o binding de libtorrent necessários.

## Primeira configuração

- Abra o Gerenciador de Conexões: `Ctrl+Shift+C` (ou ícone da bandeja -> Trocar perfil -> Gerenciador de Conexões...).
- Adicione um perfil e conecte:
  - **Local** — gerencia torrents por libtorrent neste PC (perfil padrão na primeira execução).
  - **Remoto** — aponte para qBittorrent, Transmission ou rTorrent e informe credenciais, se necessário.

## Pesquisa de torrents

Ferramentas -> Pesquisar torrents... (`Ctrl+F`) pesquisa Knaben, The Pirate Bay, EZTV, Nyaa, Torrents-CSV, LimeTorrents e BitSearch ao mesmo tempo, preenchendo a lista conforme cada fonte responde. É possível ordenar por seeders, melhor correspondência, tamanho, mais recentes ou nome; `Enter` adiciona as linhas selecionadas ao cliente conectado e `Ctrl+C` copia seus links magnet.

**Sites de pesquisa...** permite desativar indexadores individualmente, e indexadores adicionados em versões futuras são pesquisados por padrão. **Meus indexadores...** permite adicionar um endpoint Torznab ou Newznab próprio — uma instalação inteira do Prowlarr ou Jackett conta como uma única fonte. É assim que trackers privados são pesquisados: essas ferramentas já armazenam login e passkey, então o SerrebiTorrent nunca armazena a senha do tracker. O `.torrent` autenticado de um tracker privado é obtido com suas próprias credenciais no momento em que é adicionado, em vez de ser convertido em um magnet que o swarm recusaria.

O SerrebiTorrent não é distribuído com indexadores próprios configurados — apenas com as fontes públicas citadas acima. Se o [blindDL](https://github.com/serrebidev/blindDL) estiver instalado no mesmo computador e tiver indexadores configurados, a pesquisa os importa na primeira vez que é aberta, pois ambos usam o mesmo formato de feed. A importação só adiciona entradas novas: um indexador editado aqui nunca é sobrescrito.

## Configurações

- Sessão local + configurações do aplicativo: Ferramentas -> Configurações da sessão local... (`Ctrl+,`) (ou ícone da bandeja -> Configurações -> Configurações da sessão local...).
- Configurações do cliente remoto (habilitadas somente quando conectado): Ferramentas -> Configurações remotas do qBittorrent/Transmission/rTorrent... (ou ícone da bandeja -> Configurações -> ...).

## Magnets da área de transferência e trackers duplicados

`Ctrl+U` preenche a janela Adicionar URL com o primeiro magnet válido ou URL HTTP(S) de arquivo `.torrent` encontrado na área de transferência, inclusive URLs com parâmetros. **Preencher Adicionar URL pela área de transferência (magnets e URLs .torrent)** em Ferramentas -> Configurações da sessão local -> Geral controla esse comportamento e vem ativado por padrão.

Para abrir automaticamente a janela Adicionar torrent quando um magnet for copiado, ative **Abrir automaticamente a janela Adicionar torrent para magnets da área de transferência** em Ferramentas -> Configurações da sessão local -> Geral. Essa preferência do aplicativo também vale enquanto a interface Web está em uso.

Cada magnet detectado abre a janela normal de destino. Nada é adicionado até a confirmação; Cancelar descarta aquele conteúdo da área de transferência. Vários magnets são processados um de cada vez, conteúdo inalterado não gera prompts repetidos e magnets copiados pelo próprio comando Copiar link magnet do aplicativo são ignorados.

Se o torrent já existir, o SerrebiTorrent compara os trackers do novo magnet com os trackers existentes e pergunta se deve adicionar apenas os novos. Recusar mantém o torrent inalterado.

## Executar a partir do código-fonte (desenvolvedores)

1. Instale Python 3.14.
2. `git clone https://github.com/serrebidev/SerrebiTorrent`
3. `python -m pip install -r requirements.txt`
4. Certifique-se de que a extensão `libtorrent` para Python 3.14 no Windows e suas DLLs estejam instaladas ou disponíveis no `PATH` — ela não é publicada no PyPI.
5. Inicie com: `python main.py`

## Compilação

`build_exe.bat` coordena os releases a partir da máquina Windows usada para publicação. Ele cria um ambiente limpo de compilação, instala o wheel mais recente de libtorrent para CPython 3.14 mantido localmente, empacota e verifica o Windows localmente e solicita a `root@serrebiradio.com` que compile e verifique o Linux. Pacotes de macOS associados a tags são compilados nativamente pelo GitHub Actions.

Pré-requisitos:
- Python 3.14
- Um wheel validado de libtorrent proveniente da tarefa `Libtorrent Weekly Update`
- Git + GitHub CLI (`gh auth login` concluído)
- Certificado de assinatura de código instalado
- SignTool disponível (usa o caminho padrão ou a variável `SIGNTOOL_PATH`)

Comandos:
- `build_exe.bat build` — compila, assina e cria o ZIP localmente.
- `build_exe.bat release` — incrementa a versão automaticamente, compila Windows localmente e Linux via SSH, assina, arquiva, cria tag, envia para o GitHub, cria o release e envia o manifesto de atualização.
- `build_exe.bat dry-run` — mostra o que seria feito sem modificar nada.
- `powershell -File tools\build_linux_remote.ps1 -Version X.Y.Z` — compila apenas o pacote Linux no host SSH configurado.

O versionamento usa como base a tag `vMAJOR.MINOR.PATCH` mais recente. Se nenhuma existir, começa em `v1.0.0`. Commits com `BREAKING CHANGE` ou `!:` incrementam a versão major; commits que começam com `feat` (ou contêm `feature`) incrementam a minor; os demais incrementam a patch.

A saída do Windows fica em `dist\SerrebiTorrent\`; distribua a pasta inteira, não apenas o EXE. O pacote contém seu próprio runtime de Python, libtorrent e as bibliotecas nativas realmente carregadas por esses recursos, então os usuários não precisam instalar Python nem um runtime do Visual C++ separadamente.

## Atualizador automático

O aplicativo consulta os Releases do GitHub em busca de atualizações. A verificação na inicialização pode ser ativada ou desativada em Configurações da sessão local, e também é possível executar Ferramentas -> Verificar atualizações a qualquer momento.

Fluxo de atualização:
1. Baixa o ZIP do release usando o manifesto de atualização (`SerrebiTorrent-update.json`).
2. Verifica o SHA-256 do ZIP em relação ao manifesto.
3. Verifica a assinatura Authenticode do novo `SerrebiTorrent.exe`.
4. Executa um script auxiliar oculto que espera o aplicativo encerrar, faz backup da instalação atual em `<install_dir>_backup_<timestamp>`, substitui os arquivos e reinicia o aplicativo.

A limpeza de backups é automática:
- **Padrão** — mantém 1 backup (o mais recente); a limpeza começa após um período de tolerância de 5 minutos.
- **Imediata** — defina `SERREBITORRENT_KEEP_BACKUPS=0` para apagar o backup logo após uma atualização bem-sucedida.
- **Múltiplos** — defina `SERREBITORRENT_KEEP_BACKUPS=N` para manter os N backups mais recentes.

Outras variáveis de ambiente:
- `SERREBITORRENT_TRUSTED_SIGNING_THUMBPRINTS` — lista separada por vírgulas de impressões digitais de certificados confiáveis.

Se uma atualização falhar, o backup é restaurado automaticamente. Consulte o log do atualizador em `%TEMP%\SerrebiTorrent_update_*.log` se algo der errado. O processo de atualização é executado totalmente oculto — nenhuma janela de console é exibida — e os dados em `SerrebiTorrent_Data` são preservados durante todo o processo.

## Acessibilidade e atalhos

Tudo permanece acessível pelo teclado:

- `Ctrl+Shift+C` — Gerenciador de Conexões
- `Ctrl+O` / `Ctrl+U` — Adicionar arquivo torrent / Adicionar URL ou magnet
- `Ctrl+S` / `Ctrl+P` — Iniciar / Parar torrents selecionados
- `Delete` / `Shift+Delete` — Remover / Remover junto com os dados
- `Ctrl+A` — Selecionar tudo
- `Ctrl+N` — Criar um torrent
- `Ctrl+F` — Pesquisar torrents
- `Tab` — alterna o foco entre a barra lateral e a lista de torrents; um clique duplo no ícone da bandeja restaura a janela.

Os logs ficam em `SerrebiTorrent_Data\logs`, ao lado do EXE/script no modo portátil (ou nos dados do aplicativo por usuário no modo instalado).

## Como contribuir

Pull requests são bem-vindos. Se o SerrebiTorrent foi útil, abra uma PR com uma correção ou recurso para revisão.

## Comunidade e suporte

Relate bugs e solicite recursos em [Issues](https://github.com/serrebidev/SerrebiTorrent/issues). Para dúvidas, feedback e novidades de versões, entre no [grupo SerrebiProjects no Telegram](https://t.me/SerrebiProjects).
