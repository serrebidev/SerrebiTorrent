# SerrebiTorrent Build and Release

**English** | [Português (Brasil)](BUILD.pt-BR.md)

Platform packages must be built on their native operating system. Windows is
built locally on this machine, Linux is built through SSH on
`root@serrebiradio.com`, and macOS is built by GitHub Actions.

## Commands

```bat
build_exe.bat build
build_exe.bat dry-run
build_exe.bat release
powershell -File tools\build_linux_remote.ps1 -Version 1.10.0
```

## Release Rules

- Release from `main`.
- Use `build_exe.bat release` for official releases.
- Never build Windows or Linux packages on GitHub-hosted runners.
- Windows builds must use the newest CPython 3.14 wheel in
  `%USERPROFILE%\libtorrent-build\wheels`.
- Linux builds must use the newest CPython 3.14 wheel in
  `/root/libtorrent-build/wheels` on `serrebiradio.com`.
- macOS may use GitHub's native runner and Homebrew's Python 3.15 libtorrent.
- GitHub releases must be published, never drafts.
- The release script explicitly marks the new release as latest and non-draft.
- The release script removes any remaining draft releases after publishing.
- Do not ship if the build shows unresolved warnings, errors, or dependency mismatches.

## Output

Release mode builds and signs the local Windows package, builds Linux over SSH,
creates the update manifest, commits and tags the version, and publishes both
native packages. The tag starts the macOS GitHub Actions build, which attaches
its native package to the same release.

The shipped folder contains its own Python runtime and libtorrent/OpenSSL
runtime. End users do not install Python, pip, or developer tools. Every build
runs the frozen executable with developer paths removed and refuses to package
it if libtorrent, a native dependency, a client library, or a web asset is
missing. Builds run in fresh virtual environments and reject developer packages,
legacy OpenSSL 1.1 DLLs, and redundant unvendored libtorrent DLLs in the output.
