# Public web monitor

公開Webの入口を、PCを起動していなくてもGitHub Actionsで確認するための[公開リポジトリ](https://github.com/Kanshikun/public-web-monitor)です。15分間隔のスケジュールを導入済みです。2026-09-19の[通常手動実行](https://github.com/Kanshikun/public-web-monitor/actions/runs/35432420276)で、下記3サイトすべてがGitHub runnerからHTTP 200・内容一致で成功しました（08:35:51～53 UTC、各1試行）。模擬異常のGitHub Web通知欄への到達も確認しました。本人の既読・メール到達・復旧通知は未確認です。

| 監視先 | 期待する応答 |
| --- | --- |
| `https://animeirank.com/auth/login` | HTTP 200、本文に「アニメイランク」 |
| `https://star-hunt-v2.gattsu01.chatgpt.site/` | HTTP 200、本文に「Star Hunt」 |
| `https://public-app-directory.gattsu01.chatgpt.site/` | HTTP 200、本文に「公開アプリ一覧」 |

監視サイトは`monitor.py`の固定allowlistだけです。サイトには認証なしGETを行い、Cookie・Authorization・環境変数proxyは使いません。User-Agentは`public-web-monitor/1`を維持します。公開アプリ一覧ではPython標準User-Agentがedge側で拒否されることがあるためです。redirectは追わず失敗にします。本文の読取上限は256 KiBで、本文・ヘッダー・例外の生テキストは表示しません。HTTPSの証明書検証は標準のままです。通知用のGitHub REST API通信は、下記の限定した認証付き処理として分けています。

各対象は1回成功すれば終了し、失敗時だけ5秒待って同じURLを1回再試行します。2回とも失敗した対象が1件でもあればジョブを失敗にします。socket timeoutは10秒で、全処理の厳密な期限ではありません。Actionsジョブ全体には5分の上限を設けています。結果・HTTP状態・固定分類・試行回数・UTC日時をログとJob summaryへ出します。

## 無料で運用する条件

公開GitHubリポジトリと標準の`ubuntu-latest` runnerを使用します。追加のAPIキー、外部監視サービス、有料runner、artifact、cache、パッケージインストールを必要としません。非公開化や有料runnerへの変更前には料金条件を再確認してください。既存アプリ側の通信・利用枠を無料であると保証する仕組みではありません。[GitHub Actionsの料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

workflowは毎時7・22・37・52分のUTCスケジュールと手動実行だけです。pushやPRでは自動実行しません。リポジトリが公開である場合だけジョブを実行する条件を設定済みです。同時実行で進行中のジョブを取り消さず、built-in `GITHUB_TOKEN`の権限は`contents: read`と自repoの`issues: write`だけです。通知処理のstepにのみ`GH_TOKEN`環境変数で渡し、checkoutの認証情報は保存しません。別のPATやAPIキーは登録しません。[GitHubの組込みトークン](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token)

GitHubのスケジュール実行は混雑等で遅延・取りこぼしがあり、正確な15分間隔や到達保証はありません。公開リポジトリは60日間活動がないとスケジュールが自動停止するため、月1回Actionsの直近実行と有効状態を確認してください。スケジュールはdefault branchのworkflowに対して動きます。[scheduleの仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 公開・通知の確認

1. 公開リポジトリのdefault branchへのpushと、Actionsの通常手動実行は完了済み。
2. 所有者本人のGitHub通知設定でActionsの失敗通知と通知先メールを確認する。ジョブの失敗だけでは本人への到達確認にならない。必要な購読・通知設定は本人が管理する。[Actions通知](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications)
3. 対象追加や変更時はActions → Public web monitor → Run workflowを、`simulate_failure=false`で実行する。全対象のPASSとJob summaryのUTC日時を確認する。
4. 本人が通知テストを行う場合、手動実行で`simulate_failure=true`を選ぶ。この実行は監視サイトへ通信せず`SIMULATED_FAILURE`で終了コード1を返すが、GitHub APIへ接続して専用Issueを作成・再オープンする。続けて`false`で通常実行し、全サイト成功後に同じIssueへ復旧コメントが付き、閉じられることを確認する。異常・復旧それぞれの実際の通知到達を確認して記録する。
5. 次のスケジュール実行が動くことを確認する。以後も通知設定と直近実行を定期的に確認する。

simulate-failureの既定はfalseで、scheduleから有効になることはありません。独自メールや他サービスへの通知送信は実装せず、GitHubのActions通知と専用Issueの通知を利用します。本人のメール到達・既読はAPI処理の成功とは別に確認します。

## 障害と復旧の専用Issue

`Kanshikun/public-web-monitor`内の`[monitor] Public web availability`というIssueを1件だけ使います。障害は既存の「各サイトで2回とも失敗」の判定を維持します。

| 状態 | 操作 |
| --- | --- |
| 最初の障害 | 固定本文・識別markerを持つIssueを作り、所有者`Kanshikun`1名をassigneeにする |
| 同じ障害が継続 | 開いているIssueを確認するだけ。追加Issue・コメントを作らない |
| 全サイトが正常へ復帰 | 同じIssueへ固定の`RECOVERED`コメントを1回投稿し、closeする |
| 後日の新しい障害 | 以前の同じIssueをreopenし、新しい障害の識別番号を記録する |

対象はrepo、完全一致のtitle、専用body marker、作成者`github-actions[bot]`、ownerだけのassigneeを照合し、変更直前にも読み直します。似た名前の他者のIssueや他repoを操作しません。複数候補・所有条件の不一致・一覧を読み切れない場合は、推測で作成・closeせず固定エラーで停止します。公開repoのwatcher等が独自の通知設定で更新を受け取る場合はありますが、自動で担当指定するのは所有者1名だけです。

復旧コメントには障害開始run IDと実行attempt番号を組み合わせた非秘密識別markerを付けます。同じworkflowの再実行も新しい障害として識別できます。コメント成功後にcloseが失敗しても、次回は既存コメントを確認して重複投稿せずcloseを再試行します。コメント一覧の読取後とclose直前にもIssueの担当・状態・識別番号を再確認します。APIエラー時には生エラー・本文・tokenをログへ出さず`ISSUE_NOTIFICATION_FAILED`とし、jobを失敗にします。次回実行で実際のIssue状態を読み直します。

GitHub APIの接続先は公式`https://api.github.com/repos/Kanshikun/public-web-monitor/issues`配下だけで、proxy・redirectなし、socket timeout 10秒、応答上限512 KiBです。1一覧は100件ずつ最大5ページまで読み、末尾を確認できた場合だけ変更します。5ページすべて100件の場合は停止します。API版は`2026-03-10`です。[Issue API](https://docs.github.com/en/rest/issues/issues)、[コメントAPI](https://docs.github.com/en/rest/issues/comments)

scheduleの通知先はworkflow作成者で、cronを変更した利用者や無効化後に再有効化した利用者へ変わる場合があります。所有者本人の操作と通知設定を確認し、手動の模擬失敗通知が届いただけで将来のschedule通知も保証されたとは扱いません。[通知先の仕様](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)

## ローカル検証

Python標準ライブラリだけを使います。テストは架空応答を使い、実サイトへ接続しません。

```bash
python3 -m unittest discover -s tests -v
python3 monitor.py
python3 monitor.py --simulate-failure
```

2行目は実サイトへの確認、3行目は通信なしの意図的失敗です。ローカル既定ではIssue通知を行いません。workflowだけが`--github-issues`を明示し、このrepoのActions環境とbuilt-in tokenで動きます。`GITHUB_STEP_SUMMARY`がないローカル実行ではファイルを作成しません。対象追加や期待文字列の変更は、allowlistとテストをレビューしてから反映します。

この監視が確認するのは公開入口の応答だけです。Googleログイン、APIキーの有効性、DB保存、バックアップ復元、メール送信は別の検証として管理します。


## 2026-09-19の通知試験

[模擬失敗 run 35432517749](https://github.com/Kanshikun/public-web-monitor/actions/runs/35432517749)の後、所有者のGitHub通知APIでこのrepoの `ci_activity` と失敗通知タイトルを確認した。通常設定へ戻した[run 35432580821](https://github.com/Kanshikun/public-web-monitor/actions/runs/35432580821)は成功。復旧通知の到達は確認できていない。

上記は専用Issue導入前のActions標準通知の実績である。専用Issueによる障害・復旧通知はコードと架空API応答テストを追加した段階で、実際のworkflowと通知到達の検証結果は別途追記する。

workflowはactive、cron定義は保存済み。ここまでの実行証跡は手動実行であり、最初のschedule実行を観測した証拠とは区別する。


## 障害・復旧Issueの実到達確認

2026-09-19、[模擬障害run35433536604](https://github.com/Kanshikun/public-web-monitor/actions/runs/35433536604)で[専用Issue #1](https://github.com/Kanshikun/public-web-monitor/issues/1)を作成し、所有者のGitHub通知欄にassign通知が届いたことをAPIで確認した。この障害は通知試験で、サイト障害ではない。

[通常復帰run35433560287](https://github.com/Kanshikun/public-web-monitor/actions/runs/35433560287)は3サイトの検査が成功し、同じIssueへRECOVEREDコメントを1件追加してcloseした。通知欄も復旧イベント後に更新されたことを確認した。Issueは現在closed。メール到達・本人の既読は未確認である。ローカルとGitHub runnerの21テストも成功している。
