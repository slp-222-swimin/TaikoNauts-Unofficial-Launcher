# 「Management」機能の追加とZIP Importの統合について

本資料は、TJA楽曲や段位向けファイルをGUIから一括で管理する「Management」機能の作成と、その機能内で開いているフォルダにzipファイルをドロップしてその階層にインポートできるといった「ZIP Import」機能の統合についての計画書である。

合わせてこちらも参考にしてほしい：https://taikonauts-docs.pages.dev

## 「Management」機能の概要

Management 機能は TaikøNauts における以下のような項目を一元管理することができる機能である。ここでいう「管理」とは、

- `box.def` を用いた演奏ゲーム内フォルダ管理（フォルダ in フォルダ不可）
- `.tja` , `.osu` ファイル（osu!taikoのみ）の基本情報取得や管理
    * `DEMOSTART:` の位置からの音源プレビューの再生を再生マーク等でできるように
- `dan.def` を用いた段位道場カテゴリ管理（フォルダ in フォルダ不可）
- `dan.json` の基本情報取得や管理
    * このファイルによって束ねられた `.tja` 譜面の基本情報取得をする
    * `DEMOSTART:` の位置からの音源プレビューの再生を再生マーク等でできるように
- `.zip` , `.osz` ファイルをドロップして現在開いているフォルダに解凍する機能
    * `.zip` と `.osz` は内部的に同じであるため、 `.osz` の場合は `.zip` に変換してから従来通りの解凍処理を実行

### 表示形式

#### 演奏ゲーム
```txt
（box.def名） （展開ボタン）
    TITLE - SUBTITLE - MAKER （展開ボタン）
        COURSE - LEVEL
```

#### 段位道場
```txt
（dan.def名） （展開ボタン）
    "title"※1 （展開ボタン）
        TITLE - SUBTITLE - MAKER - COURSE - LEVEL※2
```

※1:""で囲ったものは `dan.def` のJSONキー名

※2:"danSongs/path" *相対パス で指定されたtjaパスから取得したもの。また、 `"danSongs/isHidden": true` なら、すべての情報を「???」という固定文字列で置換する

## `.tja` と `.osu` 形式対応表

ここでは、 TaikøNauts で読み込める譜面ファイルである `.tja` と `.osu` のラベルがどのように対応しているかを示す。基本的に、本資料では `.tja` を基準にしているためである。また、両形式**すべてが `ラベル名:値` 
の構造になっている**。

### メインヘッダー

| tjaラベル名 | osu!ラベル名 | 特徴 |
| --- | --- | --- |
| TITLE | TitleUnicode | 曲名 |
| SUBTITLE | ArtistUnicode | サブタイトル |
| OFFSET | AudioLeadIn | 曲の開始位置秒 |
| DEMOSTART | PreviewTime | プレビューの開始位置。**tjaでは秒、osu!ではミリ秒単位になる** |
| WAVE | AudioFilename | 音源ファイルの相対パス |
| MAKER | Creator | 譜面制作者名 |
| COURSE | Version | 難易度名 |

### サブヘッダー

| tjaラベル名 | osu!ラベル名 | 特徴 |
| --- | --- | --- |
| LEVEL | OverallDifficulty | 難易度 |