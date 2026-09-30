# ヘルスラボ / HEALTH LAB

体をいたわり、心を観察する、登録不要のWebアプリ。

公開版: https://toriumis.com/health-lab/

## 機能
- 体の余力・心の状態・任意の睡眠時間から今日の一歩を選ぶ
- 休息・活動・食事・つながり・気づきの実践記録
- 1/3/5/10分の自然な呼吸の瞑想タイマー、中途終了にも対応
- 事実・気持ち・次の一歩・感謝の内省日記
- 過去7日の振り返り、JSON書き出し・読み込み・削除
- Androidでインストール可能なPWA、オフライン対応

記録はlocalStorageに保存。外部送信、分析SDK、課金、アカウント、広告なし。配信基盤のアクセスログは別途存在し得ます。同一オリジンのスクリプトからはブラウザ保存領域にアクセスできるため、端末内保存は暗号化や認証を意味しません。共有端末の利用には注意してください。バックアップJSONには日記が含まれます。

## 開発
依存ライブラリ・ビルドは不要。
```
mkdir -p public/health-lab
cp index.html app.js style.css sw.js manifest.webmanifest icon.svg icon-192.png icon-512.png public/health-lab/
python3 -m http.server 8000 --directory public
```
http://localhost:8000/health-lab/ を開く。パス `/health-lab/` 前提です。他のパスで公開する場合は、manifestとservice worker登録・キャッシュURLを合わせて変更してください。PWAとservice workerはHTTPSかlocalhostで動作します。

Android: Chromeのメニューから「ホーム画面に追加」または「アプリをインストール」。Google Play向けAPKは含みません。

## 実践の限界
医療・診断・治療・悟りの判定を提供しません。WHOとNCCIHの一次資料へのリンクをアプリ内に掲載。瞑想に不快な反応があれば中止し、治療を置き換えないことを案内しています。

## ライセンス
MIT。Copyright (c) 2026 Studio Toriumi
