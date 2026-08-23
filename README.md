# Sign Checker PWA

スマホのホーム画面に追加して使えるサイン会チェッカーです。

## 主な機能
- サイン会 / 原画・一点物 / サイン本の一覧
- 先着・緊急度ベースの優先表示
- 既読 / 除外 / お気に入り
- ウォッチリスト
- PWA / オフライン閲覧
- 既存FastAPIバックエンドに接続可能

## GitHub Pages
このリポジトリには GitHub Pages 用の Actions ワークフローを含めています。

公開URLの想定:
`https://nishikohe.github.io/sign-checker-pwa/`

> GitHub Free で private repository のまま Pages を利用できない場合は、repository を Public に変更するか、Cloudflare Pages / Netlify などへデプロイしてください。

## バックエンド接続
設定画面で API ベースURLを入力すると、以下を利用します。
- `GET /api/items`
- `POST /api/collect`

デモモードではバックエンド不要です。
