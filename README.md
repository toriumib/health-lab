# ヘルスラボ / HEALTH LAB

自分の健康を、測って育てる。Mac・Android・ブラウザで使う個人の健康管理ツール。
公開版: https://toriumis.com/health-lab/

## できること
- 睡眠・歩数・運動時間・安静時心拍・体重・HRV(SDNN)を日別に記録
- 7日平均・前の7日平均・30日推移。未測定はゼロと区別
- 日別CSV読み込み（プレビュー・欠測を保持）、CSV書き出し
- 自分で作る毎日のルーティン、体調チェック、瞑想、内省日記
- 7/14/28日の生活習慣実験。開始前7日との平均比較、中止条件、結論の記録
- Mac作業中の休憩タイマー、明示的に許可した場合だけブラウザ通知
- Web画面から7日分のカレンダーICS作成（通知なし・手動読み込み）
- Mac内でApple Health XMLを日別CSVにするPythonツール（mac/）
- 相談用30日レポート、全データJSONバックアップ
- PWAインストール、Web画面のオフライン利用

不老不死・病気の診断や治療・生物学的年齢・悟り度の判定を提供しません。
Bryan Johnsonの個人プロトコルとNIH/WHOの一般的指針を区別してリンクしています。
実験の前後差は個人の観察であり、因果効果を証明しません。

## データ
localStorageの既存 health-lab-v1 キーを使用。旧版の日記・実践は保持します。
JSON形式の version は旧バックアップ互換の1。拡張 fields: days[*].measurements / routine / experiments / timerSessions。
ブラウザ保存は暗号化や認証を意味しません。Toriumis.com全体で同一オリジンの保存領域を共有するため、同じサイトのスクリプトからアクセス可能です。拡張機能・共有端末・クラウド同期の保管先に注意。
記録の外部送信、AI送信、分析SDK、課金、アカウント、広告なし。配信サービスのアクセスログは別途残り得ます。

CSV列: date,sleep_hours,steps,exercise_min,resting_hr,weight_kg,hrv_ms,note
- date: YYYY-MM-DDの実在日、未来は読み込み不可。
- 数値の空欄は既存測定を保持。同じ日付・指標は読み込む値で置き換え。
- HRVはSDNN。別アルゴリズムの値と混ぜないでください。
- Apple Health睡眠は暦日の0時で分割。手入力「昨夜」の合計とは集計範囲が違います。
- 手入力フォームの空欄保存は、その日の対応値を削除します。
- グラフは測定のある日だけ表示し、欠測の間を線で結びません。

## 開発
依存・ビルドなし。Python3で静的配信できます。
```
mkdir -p public/health-lab
cp index.html app.js health-core.js style.css sw.js manifest.webmanifest icon.svg icon-192.png icon-512.png mac-health-toolkit.zip public/health-lab/
python3 -m http.server 8000 --directory public
```
http://localhost:8000/health-lab/ を開く。HTTPSまたはlocalhostでservice workerが動きます。別のパスに変える場合は、登録パス・manifest・cache URLも変更。

```
node --test health-core.test.cjs
python3 -m unittest discover -s mac -p test_toolkit.py -v
```

Mac: Safariの「ファイル→Dockに追加」またはChromeのアプリインストール。
Android: Chromeの「ホーム画面に追加」/「アプリをインストール」。Google Play APKではありません。
休憩はページを開いている間だけ。スリープ中の通知時刻は保証されません。
Macツールの詳しい使い方は [mac/README.md](mac/README.md)。自動同期・常駐・OS設定変更はしません。

## ライセンス
MIT / Copyright (c) 2026 Studio Toriumi
