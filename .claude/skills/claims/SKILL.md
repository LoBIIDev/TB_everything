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
   git pull --rebase --autostash
   ```

2. **新增認領**：
   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/USER/anaconda3/python.exe add_claim.py "<player>" "<unit1>" "<unit2>" ...
   ```
   或用逗號分隔字串：
   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/USER/anaconda3/python.exe add_claim.py "<player>" "<unit1>, <unit2>, <unit3>"
   ```

3. **本地 generate HTML**（cache 內已有最近一次 Task Scheduler 抓的 roster，generate 很快、不用再 fetch）：
   ```bash
   PYTHONIOENCODING=utf-8 /c/Users/USER/anaconda3/python.exe generate_html.py
   PYTHONIOENCODING=utf-8 /c/Users/USER/anaconda3/python.exe line_message.py
   ```

4. **commit + push**：
   ```bash
   git add claims.yaml docs/index.html docs/line_message.txt
   git commit -m "claims: <player> 新增 N 隻"
   git push
   ```

完成後告訴使用者：
- 哪些角色被加入了（add_claim.py 的輸出已經會列）
- 新版 HTML 已直接 push，約 30 秒後 https://lobiidev.github.io/TB_everything/ 會生效

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
- GitHub Actions 已停用——更新完全靠本機 Task Scheduler（每 3 小時自動 fetch+regenerate）+ /claims 的即時 generate
- 本機 cache TTL 6 小時，generate_html.py 直接讀 cache 不會打 API，所以非常快
