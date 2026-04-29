from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files('chardet')
hiddenimports = collect_submodules('chardet.pipeline')
