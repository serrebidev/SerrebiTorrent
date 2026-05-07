# SerrebiTorrent Build and Release

Use `build_exe.bat` for all Windows build and release work.

## Commands

```bat
build_exe.bat build
build_exe.bat dry-run
build_exe.bat release
```

## Release Rules

- Release from `main`.
- Use `build_exe.bat release` for official releases.
- GitHub releases must be published, never drafts.
- The release script explicitly marks the new release as latest and non-draft.
- The release script removes any remaining draft releases after publishing.
- Do not ship if the build shows unresolved warnings, errors, or dependency mismatches.

## Output

Release mode builds the PyInstaller onedir app, signs `SerrebiTorrent.exe`, creates the release ZIP, writes `SerrebiTorrent-update.json`, commits the version bump, tags and pushes Git, and publishes the GitHub release.
