# Public web monitor

公開Webの入口を、PCを起動していなくてもGitHub Actionsで確認するための[公開リポジトリ](https://github.com/Kanshikun/public-web-monitor)です。15分間隔のスケジュールを導入済みです。2026-09-19の[通常手動実行](https://github.com/Kanshikun/public-web-monitor/actions/runs/35432420276)で、下記3サイトすべてがGitHub runnerからHTTP 200・内容一致で成功しました（08:35:51～53 UTC、各1試行）。通知の本人への到達は未確認です。

| 監視先 | 期待する応答 |
| --- | --- |
| `https://animeirank.com/auth/login` | HTTP 200、本文に「アニメイランク」 |
| `https://star-hunt-v2.gattsu01.chatgpt.site/` | HTTP 200、本文に「Star Hunt」 |
| `https://public-app-directory.gattsu01.chatgpt.site/` | HTTP 200、本文に「公開アプリ一覧」 |

対象は`monitor.py`の固定allowlistだけです。認証なしGETを行い、Cookie・Authorization・環境変数proxyは使いません。User-Agentは`public-web-monitor/1`を維持します。公開アプリ一覧ではPython標準User-Agentがedge側で拒否されることがあるためです。redirectは追わず失敗にします。本文の読取上限は256 KiBで、本文・ヘッダー・例外の生テキストは表示しません。HTTPSの証明書検証は標準のままです。

各対象は1回成功すれば終了し、失敗時だけ5秒待って同じURLを1回再試行します。2回とも失敗した対象が1件でもあればジョブを失敗にします。socket timeoutは10秒で、全処理の厳密な期限ではありません。Actionsジョブ全体には5分の上限を設けています。結果・HTTP状態・固定分類・試行回数・UTC日時をログとJob summaryへ出します。

## 無料で運用する条件

公開GitHubリポジトリと標準の`ubuntu-latest` runnerを使用します。追加のAPIキー、外部監視サービス、有料runner、artifact、cache、パッケージインストールを必要としません。非公開化や有料runnerへの変更前には料金条件を再確認してください。既存アプリ側の通信・利用枠を無料であると保証する仕組みではありません。[GitHub Actionsの料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

workflowは毎時7・22・37・52分のUTCスケジュールと手動実行だけです。pushやPRでは自動実行しません。リポジトリが公開である場合だけジョブを実行する条件を設定済みです。同時実行で進行中のジョブを取り消さず、tokenの権限は`contents: read`のみ、checkoutの認証情報も保存しません。

GitHubのスケジュール実行は混雑等で遅延・取りこぼしがあり、正確な15分間隔や到達保証はありません。公開リポジトリは60日間活動がないとスケジュールが自動停止するため、月1回Actionsの直近実行と有効状態を確認してください。スケジュールはdefault branchのworkflowに対して動きます。[scheduleの仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 公開・通知の確認

1. 公開リポジトリのdefault branchへのpushと、Actionsの通常手動実行は完了済み。
2. 所有者本人のGitHub通知設定でActionsの失敗通知と通知先メールを確認する。ジョブの失敗だけでは本人への到達確認にならない。必要な購読・通知設定は本人が管理する。[Actions通知](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications)
3. 対象追加や変更時はActions → Public web monitor → Run workflowを、`simulate_failure=false`で実行する。全対象のPASSとJob summaryのUTC日時を確認する。
4. 本人が通知テストを行う場合、手動実行で`simulate_failure=true`を選ぶ。この実行はサイトへ通信せず`SIMULATED_FAILURE`で終了コード1を返す。実際に届いた通知を本人が確認して、通知経路の確認完了を記録する。
5. 次のスケジュール実行が動くことを確認する。以後も通知設定と直近実行を定期的に確認する。

simulate-failureの既定はfalseで、scheduleから有効になることはありません。Issue作成、コメント、独自メール、他サービスへの通知送信は実装していません。GitHub Actions標準通知だけを利用します。

scheduleの通知先はworkflow作成者で、cronを変更した利用者や無効化後に再有効化した利用者へ変わる場合があります。所有者本人の操作と通知設定を確認し、手動の模擬失敗通知が届いただけで将来のschedule通知も保証されたとは扱いません。[通知先の仕様](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)

## ローカル検証

Python標準ライブラリだけを使います。テストは架空応答を使い、実サイトへ接続しません。

```bash
python3 -m unittest discover -s tests -v
python3 monitor.py
python3 monitor.py --simulate-failure
```

2行目は実サイトへの確認、3行目は通信なしの意図的失敗です。`GITHUB_STEP_SUMMARY`がないローカル実行ではファイルを作成しません。対象追加や期待文字列の変更は、allowlistとテストをレビューしてから反映します。

この監視が確認するのは公開入口の応答だけです。Googleログイン、APIキーの有効性、DB保存、バックアップ復元、メール送信は別の検証として管理します。
