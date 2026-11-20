---
name: foreman
description: >-
  派工給較便宜的模型。預設不要派：一般的多檔案實作，主模型自己做比較便宜。只在三種情況用：
  (1) 要讀或搜尋大量檔案，結果會塞滿主線；(2) 長時間的執行和等待（訓練、sweep、Colab）；
  (3) 這個對話已經很長，而接下來有一批規格明確、可以各自驗證的工作。使用者說「派出去做」「分工」時也用。
  獨立驗證用 verify skill，不是這個。Delegate work to cheaper subagent models only when reading volume,
  long waits or an already-large main context make it pay.
---

# foreman：派工

你是工頭：把工作派給夠用的最便宜模型、**親自驗收**、整合。

**預設是自己做。** 每派一次子代理都要付一筆固定開銷（子代理的系統提示和工具清單，視環境從一兩萬到七八萬 token），
第一次實跑時這筆開銷佔了子代理總用量的 75%，四個實作單元由主模型自己做會更便宜。所以派工只在划算的時候做。

本檔所在資料夾記為 `<skill>`。帳本工具是 `python <skill>/scripts/foreman.py`，下文簡寫成 `foreman`
（Windows 用 `python` 或 `py`，macOS／Linux 用 `python3`）。

**repo 自己的規則永遠優先**（CLAUDE.md、AGENTS.md、它指定的 skill）。本檔只管怎麼派工。

## 1. 該不該派

符合下面任一種才派，並用一句話告訴使用者是哪一種：

| 情況 | 派什麼 | 為什麼划算 |
|---|---|---|
| **大量閱讀或搜尋**：要讀幾十個檔、翻長 log、盤點整個 repo | 唯讀的 scout（`haiku`），只回報事實和位置 | 幾十個檔的內容不進主線，你只收結論 |
| **長時間執行和等待**：訓練、sweep、Colab、很慢的建置 | 啟動、輪詢、整理 log（`haiku`／`sonnet`） | 你不用為了等待一直醒著重讀 context |
| **主線已經很大**，又有一批規格明確的工作 | 實作 worker（`sonnet`） | 你每一次工具呼叫都在重讀整個對話，比一次派遣的固定開銷還貴 |

第三種還要過一關：把工作寫成單元，每個單元有一句目標、只能動哪些檔、完成標準 C1…Cn，而且每條標準都說得出
用哪個指令或證據判定。寫不出這樣的單元，就自己做；對話太長的問題改用 handoff skill 換 session 解決。

不派的情況：需要判斷的事（設計取捨、找根因、還沒跟使用者定案的事）永遠自己做；
幾次工具呼叫做得完的事自己做；環境不能指定子代理模型時自己做。

**只派一兩個唯讀或等待型的子代理時，不需要開帳本**，照第 2、4、5 節派出去、讀回報就好。
派多個會改檔的 worker 時才用第 3 節的完整流程。

## 2. 模型分層

用 Agent 工具的 `model` 參數指定，**每一次派遣都要明寫**（不寫會繼承你的模型，等於沒省）。

| 層 | 模型 | 給它做 |
|---|---|---|
| T0 | `haiku` | 搜尋、盤點、照規格的機械修改、跑指令、輪詢、依標準逐條核對 |
| T1 | `sonnet` | 規格明確的實作、寫測試、根因已知的修正、1～3 個檔案的重構 |
| T2 | `opus` | 跨檔重構、找根因、狀態機或並行邏輯、存檔與安全相關 |
| 你 | 主模型 | 規劃、分派、驗收、整合、跟使用者討論 |

調整：標準全部能用指令檢查 → 可降一層；錯了很難被發現 → 升一層；主模型是 Opus 時 T2 單元通常自己做。

## 3. 完整流程（多個會改檔的 worker）

```
foreman init --task "<一句話>" --mode delegate --reason "<哪一種情況>" --main-model opus|fable [--base-tokens <量到的固定開銷>]
```

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

Agent 的 prompt 就是整份交接說明。禁止 worker 自己再派子代理、禁止留下背景程序（Colab 例外見第 10 節）、
禁止 commit 以外的 git 操作（不 push、不改分支；repo 規則不要 worker commit 的話連 commit 也不做）。

## 5. worker 回報

```json
{"unit":"U1","model":"claude-sonnet-5-5","status":"PASS|FAIL|ASK",
 "filesChanged":["src/core/bowls.ts","src/core/bowls.test.ts"],
 "criteria":[
   {"id":"C1","status":"PASS","evidence":"vitest: 14 passed (bowls.test.ts 6)","run":true,"cmd":"npx vitest run","exit":0},
   {"id":"C2","status":"PASS","evidence":"src/core/bowls.ts:31 選用材料沒勾不計入"}],
 "notDone":["刻意沒做的事，和原因"],
 "unsure":["不確定、希望工頭再看的地方"]}
```

鐵則：**寫了不等於跑了。** `[run]` 標準要有實際執行的指令和 exit 0 才能 PASS；環境跑不起來就寫 `PENDING`。
`notDone` 和 `unsure` 一定要讀：便宜模型最常在這裡老實說出問題。

## 6. 驗收

- **關卡 1（一定做，你做）**：重跑檢查指令。便宜、決定性、永遠先做。
- **獨立驗證（依風險）**：改了資料、牽涉存檔或金額、或有指令判不出來的標準時，用同一個 plugin 的 **verify skill**
  派驗證者。計畫裡寫 `gate+verifier` 的單元，要有驗證者 PASS 才能整合：
  `foreman dispatch open U1 --role verifier --model haiku`，判完 `dispatch close --model-reported <ID>`。
- 畫面好不好看、真機上能不能用，指令和驗證者都看不出來：你自己截圖看，或請使用者試。

## 7. 失敗分類與重試

失敗先分類，照順序問：

1. **規格**：標準模糊、缺背景、你的假設錯了？→ 改交接說明，同一層重派。
2. **環境**：測試本來就不穩、缺套件、狀態髒掉？→ 修環境，同一層重派。分不清楚時先當環境。
3. **能力**：規格和環境都沒問題，它就是做不對 → 升一層（或升 effort），附上失敗的嘗試和原因。
4. **無法驗證**：repo 的測試設施驗不到 → 不重派、不升級。交付能驗證的部分，其餘用
   `foreman unit set U1 surfaced --note "…"` 擱置，並告訴使用者缺什麼。

每個單元最多 3 次 worker 派遣（原始、同層重試、升級）。用完就擱置並回報，不要自己接手硬做到好，
除非那個單元小到你幾次工具呼叫就能做完，這時在最後回覆裡說明你接手了。

## 8. 有疑問時問誰

疑問往上問，一層一層：**worker 問你，你問使用者。** 猜錯的代價是一整次重派，問一句便宜得多。

- **worker → 你。** 交接說明允許 worker 在動手前或做到一半停下來問：回報的 `status` 寫 `ASK`，
  `questions` 列出問題。`foreman report` 會把問題印出來，派遣維持開著、不算一次重試。
  你回答後用 SendMessage **接續同一個子代理**（它的 context 還在，比重新派一個便宜），不要另開新的。
- **你 → 使用者。** 你能回答的只有兩種來源：使用者已經定案的事、repo 裡查得到的事實。
  兩邊都沒有答案（要選做法、要取捨、資料該長怎樣），就停下來問使用者，不要替他決定。
  小而可逆、且跟已定案的原則一致的，你可以先決定，但要在最後回覆裡列出來讓使用者否決。
- 驗證者列在 `missing` 的「無法判定」也走同一條路：你能判的你判，判不了的列給使用者。

## 9. 工作目錄

- **預設共用工作目錄**：同時最多 3 個會改檔的 worker，檔案範圍互不重疊（`--files` 寫清楚）。
  每一波結束先看 `git status` 確認沒有範圍外的改動，再整合。
- **用 worktree 的時機**：單元會搶同一個檔案、改動很大、或要各自跑會互相干擾的建置。
  自己用 `git worktree add <路徑> <baselineSha>` 開，從同一個基準開始；記得每個 worktree 要重裝相依套件。
- 唯讀的 worker（搜尋、盤點、驗證者）不受上限限制。

## 10. 長時間任務（Colab、訓練、sweep）

這類任務允許背景執行：啟動、輪詢進度、整理 log、VM 斷線重跑交給 Haiku 或 Sonnet，
搭配使用者的 colab-operator 和 colab-long-gpu-jobs skill。實驗設計、判讀結果、決定下一步、
異常結果的根因分析留在你這裡。完成標準改成「產出檔存在且指標有值」這類可檢查的條件。

## 11. 模型與成本：要量，不要猜

**每個環境第一次用，先跑同一個 plugin 的 setup skill**：它會派一個什麼都不做的 haiku 子代理，量出兩件事
（數字之後帶進 `init --base-tokens`）：

- **模型有沒有照你指定的跑。** 回報的 ID 要包含你指定的模型名稱。對不上就是被
  `CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_SUBAGENT_MODEL_FORCE` 或 agent 定義檔蓋掉了：停下來告訴使用者，不要繼續派。
- **固定開銷。** 這次派遣回傳的 token 數，就是這個環境裡「派一次」的起跳價（系統提示、工具清單）。
  環境差很多：工具和 skill 裝得多的環境可能是 7 萬，乾淨的環境只有一兩萬。

之後每一次派遣都要記下實際模型：worker 的回報有 `model` 欄位，`report` 會自動記；
驗證者的用 `dispatch close --model-reported <ID>`。跟指定的不符時工具會警告。

**token 數字的意義**：Agent 工具回傳的 token 數接近「子代理結束時的 context 大小」，不是每一輪的加總。
實際計費是每一輪重讀 context 的總和（大部分是快取讀取）。要精確金額，看 Claude Code 存下來的對話紀錄裡
每則訊息的 `model` 和 `usage`。成本行只列量得到的數字，不要換算成金額。

**省成本的做法**，依效果排序：

1. **少派幾次。** 每次派遣都付一次固定開銷，所以單元的工作量要明顯大於它。幾次工具呼叫做得完的小單元，
   併進別的單元，或自己做。三個各改一個檔的小修，派一個 worker 一起做，不要派三個。
2. **用精簡的 agent 類型。** 這個 plugin 附了 `foreman:worker`、`foreman:verifier`、
   `foreman:scout`，只帶讀寫檔和 shell，不帶 MCP 工具，固定開銷比通用型小。有裝 plugin 就用它們，
   `model` 照樣每次明寫。
3. **少幾輪。** 子代理每多一輪就重讀一次整個 context。交接說明直接給行號和必要的摘錄，
   要求第一輪一次把檔案讀完、檢查指令改完再一起跑。
4. **驗證者吃整理好的材料。** 先用一支小腳本把要驗的東西攤平成一個檔（例如每道配方的步驟和分碗結果），
   驗證者讀一個檔就能判，不要讓它自己翻 repo。多個單元可以共用一次驗證。
5. **規格寫對。** 一次規格錯誤的代價是一整次重派。動筆前先確認檔案真的在你以為的地方
   （`grep` 一下），不要憑印象寫路徑和數量。
6. **補充和小修正用接續，不要重派。** 回答 worker 的問題、請它補一個漏掉的情況，用 SendMessage 接續同一個子代理；
   只有整個做法錯了才開新的派遣。
7. **讓環境本身變輕。** 固定開銷來自子代理的系統提示：掛的 MCP 伺服器、plugin、skill 清單、repo 的 CLAUDE.md。
   專門拿來派工的 repo，關掉用不到的 MCP 伺服器和 plugin，CLAUDE.md 保持精簡。改完重新探測一次看數字。
8. **看主線的大小。** 你自己的 context 越大，你每一次工具呼叫越貴，派工越划算；
   對話剛開始、context 還小的時候，小任務自己做比較便宜。

## 12. 給使用者的最後回覆

- `foreman finish` 印出的成本行，原樣。
- 交付了什麼、擱置了什麼（附原因）。
- 驗證者或關卡抓到的問題，各一句。
- repo 出貨規則逐條的結果（如果 repo 有規定）。
- 提醒使用者：實際用過之後發現的問題數，會用 `foreman feedback <run> --issues <n>` 記回去。
  累積 5 次後用 `foreman review` 回顧，決定規則要不要調。
