---
name: setup
description: >-
  claude-foreman 的第一次設定與量測：設定子代理的預設模型、裝狀態列、量這台電腦派一次子代理的固定開銷。
  使用者說「設定 foreman」「量起跳價」「裝狀態列」，或剛裝好這個 plugin 時用。只在使用者要求時執行。
  One-time setup and measurement for the claude-foreman plugin.
---

# setup：設定與量測

每一步做之前先告訴使用者要改什麼，改 `~/.claude/settings.json` 之前先給他看差異、等他同意。
這個檔案是使用者的全域設定：只加下面列的鍵，不動其他內容；先讀再改，保留原有的格式。

plugin 的根目錄記為 `<plugin>`（本檔在 `<plugin>/skills/setup/`）。

## 1. 子代理的預設模型

模型自己派的子代理，沒指定模型時會沿用主模型，主模型是最貴的那個時就很浪費。在 `~/.claude/settings.json` 的 `env` 加：

```json
{ "env": { "CLAUDE_CODE_SUBAGENT_MODEL": "claude-sonnet-5-5" } }
```

- 已經有這個鍵就不要改，告訴使用者目前的值。
- 模型 ID 用目前可用的 Sonnet；不確定最新的 ID 就問使用者，或請他用 `/model` 看清單。
- 如果看到 `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`，提醒他：它會讓「派遣時指定模型」失效，驗證者就沒辦法用 Haiku。

## 2. 狀態列

狀態列顯示目前模型和 context 大小，也把大小留給提醒用的 hook 讀。

1. 把 `<plugin>/scripts/statusline.py` 複製到 `~/.claude/foreman/statusline.py`（plugin 更新後路徑會變，所以用複本）。
2. `~/.claude/settings.json` **沒有** `statusLine` 時，加：
   ```json
   { "statusLine": { "type": "command", "command": "python3 ~/.claude/foreman/statusline.py" } }
   ```
   Windows 用 `python`，路徑寫完整的 `C:/Users/<名字>/.claude/foreman/statusline.py`。
3. **已經有** `statusLine` 時不要覆蓋。告訴使用者兩個選擇：換成這一支；或保留他的，提醒功能改用對話紀錄估算
   （比較不準，但能用）。

## 3. 量固定開銷

派子代理的起跳價每個環境差很多，量了才知道派工在這台電腦划不划算。在同一則訊息裡派兩個探測：

- A：`subagent_type` 用通用型（`general-purpose`），`model: "haiku"`
- B：`subagent_type` 用 `foreman:verifier`，`model: "haiku"`

兩個的 prompt 都是：

> 不要使用任何工具。只回覆一行 JSON：{"model":"<你的環境資訊裡寫的確切模型 ID；沒寫就填 unknown>"}

記下各自回報的模型和 Agent 工具回傳的 token 數，然後回報：

| 項目 | 結果 | 怎麼看 |
|---|---|---|
| 通用型起跳價 | <A 的 token> | 模型自己派子代理時，每次至少付這麼多 |
| 精簡型起跳價 | <B 的 token> | verify 和 foreman 用的類型 |
| 回報的模型 | <ID> | 要包含 haiku。不是的話，指定模型被環境變數或設定蓋掉了，先解決這個 |

判讀：起跳價在一兩萬，驗證和派工都便宜，可以放心用；在五萬以上，只在 verify 和大量閱讀時派，
並檢查是不是掛了太多 MCP 伺服器或 plugin（每一個的工具說明都會進到子代理的開頭）。

把兩個數字記進這個 repo 的 CLAUDE.md 或使用者指定的地方，之後 `foreman init --base-tokens <精簡型的數字>` 會用到。

## 4. 確認提醒會出現

提醒由 plugin 的 hook 負責，裝好 plugin 就已經生效，不用另外設定。告訴使用者它只在兩種情況出聲、各說一次：

- 對話閒置超過 60 分鐘、而且 context 超過 10 萬：快取過期，這一輪會重讀全部
- context 超過 50 萬

要調門檻，在 `settings.json` 的 `env` 設 `FOREMAN_IDLE_MIN`、`FOREMAN_IDLE_TOKENS`、`FOREMAN_BIG_TOKENS`；
設 `FOREMAN_REMIND=0` 可以關掉。

## 做完後

用一張表回報：改了哪些設定、兩個起跳價、有沒有哪一步因為既有設定而跳過。提醒使用者重開 Claude Code 讓設定生效。
