# claude-foreman

給 Claude Code 用的一組省成本工具：讓貴的模型少做白工，讓便宜的模型做它擅長的事，並在該換 session 的時候提醒你。

設計原則是**越不花 token 的手段排越前面**：

| 層 | 內容 | 花費 |
|---|---|---|
| 設定 | 子代理的預設模型、狀態列顯示 context 大小 | 設一次，不花 token |
| hook | 該換 session 時提醒你 | 程式判斷，平常不出聲 |
| skill | `verify` 獨立驗證、`handoff` 交接、`foreman` 派工 | 用到才載入 |

## 安裝

```
/plugin marketplace add EndeavorYen/claude-foreman
/plugin install foreman@endeavoryen
```

裝好後在 Claude Code 裡說「設定 foreman」（或 `/foreman:setup`），它會帶你做三件事：
設定子代理的預設模型、裝狀態列、量這台電腦派一次子代理的固定開銷。

需要 Python 3.9 以上（只用標準庫），Windows、macOS、Linux 都能跑。

## 第一層：設定

- **`CLAUDE_CODE_SUBAGENT_MODEL`**：模型自己派的子代理，沒指定模型時會沿用主模型。主模型用最貴的那個時，
  這一個環境變數就是整套裡性價比最高的一步。
- **狀態列**：`[Fable 5.2] ctx 312k (31%)`。你隨時看得到 context 多大。

## 第二層：提醒

長對話每一輪都重讀全部內容。1M 的 context 夠用，所以提醒的依據不是「快滿了」，而是「這一輪會白付錢」。
只在兩種情況出聲：

| 情況 | 為什麼 |
|---|---|
| 對話閒置超過 60 分鐘，且 context 超過 10 萬 | 快取過期了，下一輪要用接近全價重讀全部。這時開新 session 幾乎沒有損失 |
| context 超過 50 萬 | 找個段落點交接 |

每次長時間閒置後提醒一次，超過 50 萬提醒一次；任務進行中不會打斷你。門檻用環境變數調：
`FOREMAN_IDLE_MIN`、`FOREMAN_IDLE_TOKENS`、`FOREMAN_BIG_TOKENS`；`FOREMAN_REMIND=0` 關掉。

## 第三層：三個 skill

### verify：獨立驗證

派一個沒參與實作、低一層的模型，拿整理好的材料逐條附證據找問題。出貨前有高風險內容時用：資料、存檔、金額，
或「合不合理、有沒有漏」這類指令檢查不出來的標準。

這是整套裡唯一有實測證據的做法（見 [`examples/mon-bakery-0.8.1.md`](examples/mon-bakery-0.8.1.md)）：
實作者回報「全部沒問題」之後，Haiku 驗證者找到 3 類真的問題。

### handoff：交接

說「交接」，Claude 把目前的狀態、已定案的決定、下一步寫進 `.claude/handoff.md`。
開新 session 說「接續」，它會被提示先讀那份檔。交接檔是明寫的，你可以檢查它留了什麼。

### foreman：派工

**預設不派。** 每派一次子代理都有固定開銷，一般的多檔案實作由主模型自己做比較便宜。只在三種情況派：
要讀或搜尋大量檔案、長時間的執行和等待（訓練、sweep、Colab）、對話已經很長又有一批規格明確的工作。

多個會改檔的 worker 同時派出去時，帳本工具會擋下違規的動作：

| 規則 | 怎麼擋 |
|---|---|
| PASS 要有證據；寫了測試不等於跑過 | `report` 檢查回報，不合格 exit 3 |
| worker 不能動範圍外的檔案 | `report` 比對 `plan add --files` |
| 不採信 worker 自己說的結果 | PASS 之前必須有主模型在回報之後跑的 `gate` |
| 每個單元最多派 3 次；失敗要先分類 | 第 4 次 `dispatch open` 被拒絕；FAIL 必須帶 `--fail-kind` |
| 要知道子代理實際跑在哪個模型 | 回報必填 `model`；跟指定的不符時警告 |
| 有疑問往上問 | worker 回報 `ASK`，派遣維持開著；主模型答不了就問使用者 |

plugin 附三種精簡的子代理類型（`worker`、`verifier`、`scout`），只帶讀寫檔和 shell，用來壓低固定開銷。

## 紀錄

放在各 repo 的 `.claude/foreman-runs/`（自動加進 `.git/info/exclude`）：

```
python skills/foreman/scripts/foreman.py review                       # 歷次驗證和派工
python skills/foreman/scripts/foreman.py feedback <編號> --issues 1   # 回填實際用過後發現的問題數
```

「驗證值不值得繼續做」「派工有沒有省到」都看這份紀錄，不靠感覺。

## 已知的限制

- 派遣回傳的 token 數是子代理結束時的 context 大小，不是計費金額。成本行只列量得到的數字。
- 精簡子代理類型能把固定開銷降多少，每個環境不同，用 setup 量。
- 提醒的閒置時間以「Claude 上一次回完話」起算。快取實際的時效依方案而定，60 分鐘是保守的預設值。
- 已在 Claude Code 2.1.329 實測：plugin 通過 `claude plugin validate`、四個 skill 和三種子代理類型都有載入、
  新 session 的交接提示和閒置提醒都會觸發並顯示。還沒實測：狀態列實際收到的資料（照文件寫的）、
  Windows 上的 hook 指令、精簡子代理的固定開銷。
- plugin 名稱是 `foreman`（Claude Code 不允許第三方 plugin 用 `claude-` 開頭），repo 名稱維持 `claude-foreman`。
- 「便宜模型主做、強模型當顧問」是 Claude Code 內建的 `/advisor`，不在這個 plugin 的範圍。

## 開發

```
python -m unittest discover tests
```

派工流程借用了 [midego1/claude-orchestrate](https://github.com/midego1/claude-orchestrate) 的幾個想法：
規則要用工具強制、證據門檻、失敗分類、重試上限。實作是重新寫的，沒有沿用它的程式碼。
