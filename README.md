# TaikøNauts UNOFFL Launcher

TaikøNauts の非公式ランチャー（Launcher）です。ゲームの起動、アップデーターの制御、スキン切り替え、および譜面ZIPファイルのドラッグ＆ドロップ展開機能を備えています。

## 主な機能

1. **ゲーム起動 (Launch Game)**
   - 設定した `TaikoNauts.exe` を起動します。

2. **アップデーターの制御 (Launch Updater)**
   - 同梱の `TaikoNautsUpdater.exe` をランチャー内の専用コンソール画面で実行します。
   - アップデーターのログ表示や、対話式の選択肢入力（Yes/Noボタンなど）に対応しています。

3. **スキン切り替え (Skins)**
   - ゲームフォルダ内の `Skins/` ディレクトリからスキンを自動検出し、一覧表示します。
   - スキンを選択して「Apply selected skin」を実行すると、ゲームの `Config/GameConfig.json` の `skinPath` が自動で書き換えられます。

4. **譜面ZIPファイルの簡単導入 (Drag & Drop)**
   - ランチャーの画面に譜面の `.zip` ファイルをドラッグ＆ドロップするだけで、ゲームフォルダ内の `Songs/zip` フォルダへ自動で解凍・展開されます。

---

## 動作環境
- **OS**: Windows (本ツールは Windows API を使用しているため Windows 専用です)
- **Python**: Python 3.10 以上 (スクリプトのまま実行する場合)

---

## 使い方

### 開発環境で実行する場合
依存関係はPythonの標準ライブラリおよび Windows API のため、追加のパッケージなしで動作します。
```bash
python main.py
```

### EXEファイル（実行ファイル）のビルド方法
PyInstaller を使用して、単一のスタンドアロンEXEファイルをビルドすることができます。

1. PyInstallerのインストール:
   ```bash
   pip install pyinstaller
   ```
2. ビルドコマンドの実行:
   ```bash
   pyinstaller --onefile --noconsole --name "TaikonautsLauncher" main.py
   ```
3. ビルド完了後、`dist/TaikonautsLauncher.exe` が生成されます。

---

## プロジェクト構成
- `main.py` : ランチャーのGUIおよび全ロジック（Tkinter使用）
- `launcher_state.json` : 選択した `TaikoNauts.exe` のパスを保存する設定ファイル
- `.gitignore` : ビルド生成物（`build/`, `dist/`, `.spec`）やPythonキャッシュを除外する設定
