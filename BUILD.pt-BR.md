# Compilação e Release do SerrebiTorrent

[English](BUILD.md) | **Português (Brasil)**

Os pacotes de cada plataforma devem ser compilados no respectivo sistema operacional nativo. O Windows é compilado localmente nesta máquina, o Linux é compilado por SSH em `root@serrebiradio.com` e o macOS é compilado pelo GitHub Actions.

## Comandos

```bat
build_exe.bat build
build_exe.bat dry-run
build_exe.bat release
powershell -File tools\build_linux_remote.ps1 -Version 1.10.0
```

## Regras de release

- Faça o release a partir de `main`.
- Use `build_exe.bat release` para releases oficiais.
- Nunca compile pacotes de Windows ou Linux em runners hospedados pelo GitHub.
- Builds de Windows devem usar o wheel mais recente de CPython 3.14 em `%USERPROFILE%\libtorrent-build\wheels`.
- Builds de Linux devem usar o wheel mais recente de CPython 3.14 em `/root/libtorrent-build/wheels` no host `serrebiradio.com`.
- O macOS pode usar o runner nativo do GitHub e o libtorrent para Python 3.14 fornecido pelo Homebrew.
- Releases do Forgejo devem ser publicados, nunca deixados como rascunho.
- O script de release marca explicitamente a nova versão como a mais recente e como não rascunho.
- O script de release remove quaisquer releases em rascunho restantes após a publicação.
- Não distribua o pacote se a compilação mostrar avisos, erros ou incompatibilidades de dependências não resolvidos.

## Saída

No modo de release, o processo compila e assina o pacote local do Windows, compila o Linux por SSH, cria o manifesto de atualização, faz commit e cria a tag da versão, e publica os dois pacotes nativos. A tag inicia a compilação de macOS no GitHub Actions, que anexa o pacote nativo correspondente ao mesmo release.

A pasta distribuída contém seu próprio runtime de Python e o runtime de libtorrent/OpenSSL. Usuários finais não precisam instalar Python, pip nem ferramentas de desenvolvimento. Cada build executa o binário congelado com os caminhos de desenvolvimento removidos e recusa o empacotamento se libtorrent, uma dependência nativa, uma biblioteca de cliente ou um recurso web estiver ausente. As compilações são executadas em ambientes virtuais novos e rejeitam pacotes de desenvolvimento, DLLs legadas do OpenSSL 1.1 e DLLs redundantes e não incorporadas do libtorrent na saída.
