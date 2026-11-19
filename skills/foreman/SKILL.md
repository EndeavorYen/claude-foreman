---
name: foreman
description: >-
  多模型派工：強模型（Opus／Fable）當工頭，把可切塊的工作派給較便宜的模型（Sonnet／Haiku），
  自己負責規劃和驗收。動手做多檔案、多步驟的實作，批次修改，大量閱讀搜尋，或長時間的執行等待
  （訓練、sweep）之前使用；先過判斷關卡，寫不出兩個能各自驗證的單元就自己做。單檔小修、
  快問快答、還在討論設計時不要用。Use before substantive multi-unit implementation work
  to decide whether to delegate to cheaper subagent models, and to run the delegation with
  evidence gates, a retry budget and a cost line.
---

# foreman：派工與驗收

你是工頭：拆工作、派給夠用的最便宜模型、**親自驗收**、整合。你的 token 最貴，留給規劃、判斷和驗收。

本檔所在資料夾記為 `<skill>`。帳本工具是 `python <skill>/scripts/foreman.py`，下文簡寫成 `foreman`
（Windows 用 `python` 或 `py`，macOS／Linux 用 `python3`）。它會**拒絕**違規的動作：
exit 2＝被規則擋下，exit 3＝關卡或回報沒過。被擋下時照訊息補做，不要繞過。

**repo 自己的規則永遠優先**（CLAUDE.md、AGENTS.md、它指定的 skill）。本檔只管怎麼派工。

## 1. 判斷關卡：先拆再判

不要用「感覺很大」決定。動手寫計畫表：

1. 把任務裡**需要判斷的部分**挑出來：設計取捨、找 bug 根因、還沒跟使用者定案的事。這些你自己做，
   而且先做完。沒定案的設計先跟使用者定案。
2. 剩下的工作，試著寫成單元。每個單元要有：一句目標、只能動哪些檔案、完成標準 C1…Cn，
   而且**每條標準都說得出用哪個指令或哪個證據判定**。
3. 判定：
   - 寫得出 **2 個以上**這樣的單元，彼此不搶同一個檔案（或有明確先後）→ **派工**（`--mode delegate`）
   - 寫不出來 → **自己做**（`--mode solo`），用一行說原因，然後照常工作
   - 環境不能指定子代理的模型（Agent 工具沒有 `model` 參數）→ 自己做

參考訊號（不是門檻）：要讀超過十幾個檔案、同一種修改橫跨很多檔案、要等很久的執行、主線 context 會被塞滿，
這些都偏向派工。只改一兩個檔案、十次以內工具呼叫做得完，偏向自己做。

兩種結果都要開帳本，判斷才有紀錄可回顧：

```
foreman init --task "<一句話>" --mode delegate|solo --reason "<為什麼>" --main-model opus|fable
```

`solo` 的話到此為止，做完跑 `foreman finish`。

## 2. 模型分層

用 Agent 工具的 `model` 參數指定，**每一次派遣都要明寫**（不寫會繼承你的模型，等於沒省）。

| 層 | 模型 | 給它做 |
|---|---|---|
| T0 | `haiku` | 搜尋、盤點、照規格的機械修改、跑指令、輪詢、依標準逐條核對 |
| T1 | `sonnet` | 規格明確的實作、寫測試、根因已知的修正、1～3 個檔案的重構 |
| T2 | `opus` | 跨檔重構、找根因、狀態機或並行邏輯、存檔與安全相關 |
| 你 | 主模型 | 規劃、分派、驗收、整合、跟使用者討論 |

調整：標準全部能用指令檢查 → 可降一層；錯了很難被發現 → 升一層；主模型是 Opus 時 T2 單元通常自己做。

## 3. 流程

```
foreman plan add U1 --objective "…" --model sonnet --effort medium --verify gate --files src/core
foreman plan add U3 --objective "…" --model sonnet --verify gate+verifier --depends U1 --files src/ui tests/e2e
foreman plan show
```

1. **貼計畫表。** 把 `plan show` 的輸出原樣貼給使用者，再開始派。沒貼就派是違規。
2. **寫交接說明**：每個單元照 `<skill>/templates/handoff.md` 寫（見第 4 節）。
3. **派工。** 每次派之前 `foreman dispatch open U1`；互不相依的單元在**同一則訊息**裡一起發多個 Agent 呼叫。
   第 4 次 worker 派遣、依賴還沒整合的單元，工具會拒絕。
4. **收回報。** worker 最後的文字就是回報（一個 JSON 區塊）。存進帳本並檢查：
   `foreman report U1 -`（把 JSON 從 stdin 餵進去）。格式不對、PASS 沒證據、動了範圍外的檔案 → exit 3。
5. **關卡 1：你自己重跑。** `foreman gate U1 --cmd "<檢查指令>" [--cwd <worktree>]`，可以給多個 `--cmd`。
   不採信 worker 自己說的結果。回報之前跑的關卡不算數。
6. **關卡 2：依風險。** 計畫寫 `gate+verifier` 的單元，派一個驗證者（第 6 節）。
7. **結案這次派遣：** `foreman dispatch close U1 --result PASS|FAIL [--fail-kind …] --tokens <n> --duration <秒>`。
   token 和時間取自 Agent 工具回傳的用量；拿不到就不填，不要估。
8. **整合**：把該單元的改動併進主線，再跑一次關卡，`foreman unit set U1 integrated`。一次整合一個。
9. **出貨關卡**：全部整合後，跑 repo 自己規定的完整檢查：`foreman gate ship --cmd "…" --cmd "…"`。
   repo 規則裡不能用指令做的項目（截圖親眼看、真機確認）由你自己做，不派出去。
10. **收尾**：`foreman finish`，把它印出的成本行原樣放進給使用者的最後回覆。

## 4. 交接說明

worker 是冷啟動的，看不到你和使用者的對話。交接說明寫不好，其他都白費。照模板填，每一格都要有：

- **目標**：一句話。
- **背景**：它需要知道的決定和原因（使用者定案了什麼）、相關檔案路徑、repo 規則裡跟它有關的條文。寧可多給。
- **範圍**：只能改哪些檔案；**明列不准碰的**（版本號、changelog、別的單元的檔案）。
- **完成標準** C1…Cn：能執行的標註 `[run]` 並寫出指令。
- **深度**：「照規格做，不要探索」或「先讀懂再動手」。
- **回報格式**：第 5 節的 JSON，其他什麼都不要。

Agent 的 prompt 就是整份交接說明。禁止 worker 自己再派子代理、禁止留下背景程序（Colab 例外見第 9 節）、
禁止 commit 以外的 git 操作（不 push、不改分支；repo 規則不要 worker commit 的話連 commit 也不做）。

## 5. worker 回報

```json
{"unit":"U1","status":"PASS|FAIL",
 "filesChanged":["src/core/bowls.ts","src/core/bowls.test.ts"],
 "criteria":[
   {"id":"C1","status":"PASS","evidence":"vitest: 14 passed (bowls.test.ts 6)","run":true,"cmd":"npx vitest run","exit":0},
   {"id":"C2","status":"PASS","evidence":"src/core/bowls.ts:31 選用材料沒勾不計入"}],
 "notDone":["刻意沒做的事，和原因"],
 "unsure":["不確定、希望工頭再看的地方"]}
```

鐵則：**寫了不等於跑了。** `[run]` 標準要有實際執行的指令和 exit 0 才能 PASS；環境跑不起來就寫 `PENDING`。
`notDone` 和 `unsure` 一定要讀：便宜模型最常在這裡老實說出問題。

## 6. 驗證

- **關卡 1（一定做，你做）**：重跑檢查指令。便宜、決定性、永遠先做。
- **關卡 2（依風險，派驗證者）**：以下才派，其他跳過：
  - 有標準沒辦法用指令判定（文案適不適合、資料合不合理、有沒有漏掉情況）
  - 牽涉存檔、資料遺失、金額、權限
  - 你在回報的 `unsure` 或 diff 裡看到疑點，但不想自己花 context 細讀
- 驗證者比實作者低一層，最低 Haiku；涉及正確性或安全的至少 Sonnet。照 `<skill>/templates/verify.md` 派：
  給它 diff 範圍和完成標準，要它**逐條附證據**判 PASS／FAIL，並列出規格漏掉的情況。沒有證據的 PASS 當 FAIL。
  `foreman dispatch open U1 --role verifier --model haiku`，判完 `dispatch close`。

## 7. 失敗分類與重試

失敗先分類，照順序問：

1. **規格**：標準模糊、缺背景、你的假設錯了？→ 改交接說明，同一層重派。
2. **環境**：測試本來就不穩、缺套件、狀態髒掉？→ 修環境，同一層重派。分不清楚時先當環境。
3. **能力**：規格和環境都沒問題，它就是做不對 → 升一層（或升 effort），附上失敗的嘗試和原因。
4. **無法驗證**：repo 的測試設施驗不到 → 不重派、不升級。交付能驗證的部分，其餘用
   `foreman unit set U1 surfaced --note "…"` 擱置，並告訴使用者缺什麼。

每個單元最多 3 次 worker 派遣（原始、同層重試、升級）。用完就擱置並回報，不要自己接手硬做到好，
除非那個單元小到你幾次工具呼叫就能做完，這時在最後回覆裡說明你接手了。

## 8. 工作目錄

- **預設共用工作目錄**：同時最多 3 個會改檔的 worker，檔案範圍互不重疊（`--files` 寫清楚）。
  每一波結束先看 `git status` 確認沒有範圍外的改動，再整合。
- **用 worktree 的時機**：單元會搶同一個檔案、改動很大、或要各自跑會互相干擾的建置。
  自己用 `git worktree add <路徑> <baselineSha>` 開，從同一個基準開始；記得每個 worktree 要重裝相依套件。
- 唯讀的 worker（搜尋、盤點、驗證者）不受上限限制。

## 9. 長時間任務（Colab、訓練、sweep）

這類任務允許背景執行：啟動、輪詢進度、整理 log、VM 斷線重跑交給 Haiku 或 Sonnet，
搭配使用者的 colab-operator 和 colab-long-gpu-jobs skill。實驗設計、判讀結果、決定下一步、
異常結果的根因分析留在你這裡。完成標準改成「產出檔存在且指標有值」這類可檢查的條件。

## 10. 第一次在某個環境用

先確認兩件事，確認不了就在最後回覆裡照實說：

- 子代理真的跑在指定的模型上：第一個派遣回來後看 Agent 工具回報的模型。
  `CLAUDE_CODE_SUBAGENT_MODEL` 這類環境變數可能蓋掉你的指定。
- 拿得到子代理的 token 用量。拿不到的話成本行只有派遣次數和時間，照實呈現。

## 11. 給使用者的最後回覆

- `foreman finish` 印出的成本行，原樣。
- 交付了什麼、擱置了什麼（附原因）。
- 驗證者或關卡抓到的問題，各一句。
- repo 出貨規則逐條的結果（如果 repo 有規定）。
- 提醒使用者：實際用過之後發現的問題數，會用 `foreman feedback <run> --issues <n>` 記回去。
  累積 5 次後用 `foreman review` 回顧，決定規則要不要調。
