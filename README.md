# kansai-museum-feed

関西ミュージアム特別展リスト用の軽量JSONフィードです。

## 自動更新

GitHub Actionsが公式サイトだけを1日1回確認します。取得失敗時は既存データを維持し、
内容に意味のある変更がない日はコミットしません。取得結果は7日間のActions artifact
`museum-collection-report` に保存されます。

取得元と自動公開の可否は `config/sources.json` で管理します。
`autoPublish: false` の館は候補レポートだけを作り、`exhibitions.json` を変更しません。

みんぱくは公式サイトからの取得候補を先に確認するため、初期状態ではプレビュー専用です。
公式サイトが送信していない中間CA証明書は、SECOM公式配布版を
`certs/nii-odca4g8rsa-pem.cer` に固定し、みんぱくへの接続時だけ追加します。
証明書・期限・ホスト名の検証は維持し、SSL検証の無効化は行いません。
`minpaku` の取得結果を確認するまでは `autoPublish` を `true` にしません。

## ローカル確認

```sh
python3 -m unittest discover -s tests -v
python3 scripts/update_feed.py
```
