---
name: claims
description: 登錄/查看 SWGoH 公會 TB Operation 認領資訊。當使用者輸入 /claims 並提供玩家識別（ally_code 或暱稱）+ 角色清單時觸發；自動寫入 claims.yaml、重新生成網頁、commit & push。也可只查看現有認領（不帶角色清單時）。
---

# /claims — 公會認領登錄

當使用者要登錄一筆認領（某玩家正在準備某些角色到 R9）或查看現有認領時觸發。

## 輸入解析

使用者輸入大致是：`/claims <player> <unit1>, <unit2>, ...`

- `<player>`：可以是
  - **ally_code**（9 位數字，例如 `749294592`）
  - **暱稱/顯示名**（公會 LINE 慣用名，會以 case-insensitive contains 比對 swgoh.gg 上的名字）
- `<unit1>, <unit2>...`：用逗號（`,` 或 `、`）或空白分隔
  - 可用英文（`Echo`、`Eeth Koth`）
  - 可用 `unit_alias.json` 的簡稱（`易思考斯`、`豪斯士兵`）
  - 可用 `unit_zh.json` 的繁中全名

如果使用者只輸入 `/claims`（無參數），就 `cat claims.yaml` 顯示目前所有認領。

如果使用者只輸入 `/claims <player>`（無角色），先試著登錄空清單（不要做），改為列出該玩家現有認領。

## 步驟

切到專案目錄（如果還不在）：
```bash
cd C:/Users/USER/Documents/Projects/swgoh_TB
```

1. **先 pull 最新**（確保不衝突）：
   ```bash
   git pull --rebase
   ```

2. **新增認領**（最常見情境）：
   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/USER/anaconda3/python.exe add_claim.py "<player>" "<unit1>" "<unit2>" ...
   ```
   或用逗號分隔字串：
   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/USER/anaconda3/python.exe add_claim.py "<player>" "<unit1>, <unit2>, <unit3>"
   ```

3. **commit + push**（**只推 claims.yaml**，不本地 generate HTML）：
   ```bash
   git add claims.yaml
   git commit -m "claims: <player> 新增 N 隻"
   git push
   ```

   **不要在本機跑 `generate_html.py` 也不要 push `docs/index.html`**。原因：本機 `cache/` 抓不到（curl_cffi 裝不起來），用舊 cache 產出的 HTML 會比雲端的舊。`claims.yaml` 一被 push，GitHub Actions（`.github/workflows/update.yml` 已設 `push.paths: claims.yaml` trigger）會用雲端 fresh fetch 跑完整 fetch+generate+push，約 1-2 分鐘 GitHub Pages 上會出現最新資料 + 新認領的 HTML。

完成後告訴使用者：
- 哪些角色被加入了（add_claim.py 的輸出已經會列）
- GitHub Actions 已被觸發，約 1-2 分鐘後 https://lobiidev.github.io/TB_everything/ 會看到含新認領的最新版

## 範例

User: `/claims Goodnew 50R-T, Echo, 易思考斯, 豪斯士兵`

執行後預期 add_claim.py 輸出：
```
✓ Goodnew: 新增 4 隻 (重複略過 0)
  新增：50R-T, Echo, Eeth Koth, Hoth Rebel Soldier
  該玩家目前認領清單：50R-T, Echo, Eeth Koth, Hoth Rebel Soldier
```

User: `/claims 749294592 JKL GMY`

→ ally_code 749294592 = 老 Mol 的第二個春天，登錄 Jedi Knight Luke Skywalker + Grand Master Yoda。

User: `/claims`

→ `cat claims.yaml` 列出所有現有認領。

## 注意事項

- 名稱無法解析時 add_claim.py 會 warn 但仍記錄（之後不會自動 prune）
- 暱稱模糊比對若同時對到多人會 abort 並列出候選名單，請改用 ally_code 或更精確的字串
- pull --rebase 是因為 GitHub Actions 可能在這之間 push 了 docs/index.html
